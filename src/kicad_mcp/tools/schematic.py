"""Schematic tools with parser-based reads and transactional writes."""

from __future__ import annotations

import json
import math
import re
import uuid
from collections.abc import Callable, Iterable
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Literal, Protocol, TypedDict, cast

import structlog
from mcp.server.fastmcp import FastMCP

from ..config import get_config
from ..connection import KiCadConnectionError, get_kicad
from ..models.schematic import (
    AddBusInput,
    AddBusWireEntryInput,
    AddLabelInput,
    AddNoConnectInput,
    AddSymbolInput,
    AddWireInput,
    AnnotateInput,
    AutoPlaceSymbolsInput,
    CreateSheetInput,
    DeleteSymbolInput,
    DeleteWireInput,
    GetSheetInfoInput,
    GlobalLabelInput,
    HierarchicalLabelInput,
    MoveSymbolInput,
    PowerSymbolInput,
    RouteWireBetweenPinsInput,
    TraceNetInput,
    UpdatePropertiesInput,
)
from ..utils.cache import clear_ttl_cache, ttl_cache
from ..utils.schematic_router import RouterBBox, SchematicRouter
from ..utils.sexpr import (
    _escape_sexpr_string,
    _extract_block,
    _sexpr_string,
    _unescape_sexpr_string,
)
from .metadata import headless_compatible

SCHEMATIC_GRID_MM = 2.54
SNAP_TOLERANCE_MM = 1e-6
AUTO_LAYOUT_ORIGIN_X_MM = 50.8
AUTO_LAYOUT_ORIGIN_Y_MM = 50.8
AUTO_LAYOUT_COLUMN_SPACING_MM = 25.4
AUTO_LAYOUT_ROW_SPACING_MM = 17.78
AUTO_LAYOUT_COLUMNS = 4
DEFAULT_SHEET_WIDTH_MM = 30.48
DEFAULT_SHEET_HEIGHT_MM = 20.32

# KiCad paper sizes (landscape, mm).  Used for sheet-boundary clamping.
PAPER_SIZES_MM: dict[str, tuple[float, float]] = {
    "A4":     (297.0,  210.0),
    "A3":     (420.0,  297.0),
    "A2":     (594.0,  420.0),
    "A1":     (841.0,  594.0),
    "A0":     (1189.0, 841.0),
    "A":      (279.4,  215.9),   # ANSI A (letter)
    "B":      (431.8,  279.4),   # ANSI B (tabloid)
    "C":      (558.8,  431.8),
    "D":      (863.6,  558.8),
    "E":      (1117.6, 863.6),
    "USLetter": (279.4, 215.9),
    "USLegal":  (355.6, 215.9),
}
# Margin inside the sheet border kept free of symbols.
_SHEET_MARGIN_MM = 15.0
NETLIST_LAYOUT_COLUMN_SPACING_MM = 38.1
NETLIST_LAYOUT_ROW_SPACING_MM = 35.56
NETLIST_LABEL_OFFSET_MM = 10.16
NETLIST_POWER_OFFSET_MM = 17.78
POWER_NET_NAMES = {
    "GND",
    "GNDA",
    "GNDD",
    "VCC",
    "VDD",
    "VSS",
    "+1V8",
    "+2V5",
    "+3V3",
    "+5V",
    "+12V",
    "-5V",
    "-12V",
}
logger = structlog.get_logger(__name__)
_SCHEMATIC_STATE_DIRNAME = ".kicad-mcp"

SchematicCapabilityStatus = Literal["native", "wrapper_needed"]


class SchematicCapabilityEntry(TypedDict):
    kicad_sch_api_support: SchematicCapabilityStatus
    verified_surface: list[str]
    notes: str


SCHEMATIC_PUBLIC_TOOL_NAMES = (
    "sch_get_symbols",
    "sch_get_wires",
    "sch_get_labels",
    "sch_get_net_names",
    "sch_add_symbol",
    "sch_add_wire",
    "sch_add_label",
    "sch_add_power_symbol",
    "sch_add_bus",
    "sch_add_bus_wire_entry",
    "sch_add_no_connect",
    "sch_update_properties",
    "sch_build_circuit",
    "sch_get_pin_positions",
    "sch_check_power_flags",
    "sch_annotate",
    "sch_reload",
    "sch_create_sheet",
    "sch_add_hierarchical_label",
    "sch_add_global_label",
    "sch_list_sheets",
    "sch_get_sheet_info",
    "sch_route_wire_between_pins",
    "sch_add_missing_junctions",
    "sch_get_connectivity_graph",
    "sch_trace_net",
    "sch_auto_place_symbols",
)

SCHEMATIC_BACKEND_CAPABILITY_MATRIX: dict[str, SchematicCapabilityEntry] = {
    "sch_get_symbols": {
        "kicad_sch_api_support": "wrapper_needed",
        "verified_surface": [
            "ComponentCollection.get",
            "ComponentCollection.filter",
            "Component.to_dict",
        ],
        "notes": (
            "kicad-sch-api exposes component collections, but the current text surface needs "
            "a compatibility wrapper."
        ),
    },
    "sch_get_wires": {
        "kicad_sch_api_support": "wrapper_needed",
        "verified_surface": ["WireCollection.all"],
        "notes": "Wire summaries are rebuilt from the verified WireCollection API.",
    },
    "sch_get_labels": {
        "kicad_sch_api_support": "wrapper_needed",
        "verified_surface": ["LabelCollection.all"],
        "notes": (
            "kicad-sch-api exposes local labels; compatibility readers extend that "
            "surface with global and hierarchical labels."
        ),
    },
    "sch_get_net_names": {
        "kicad_sch_api_support": "wrapper_needed",
        "verified_surface": ["Schematic.get_net_for_pin", "Schematic.get_connected_pins"],
        "notes": (
            "Net-name summaries can be rebuilt from pin connectivity helpers, but require "
            "a compatibility wrapper."
        ),
    },
    "sch_add_symbol": {
        "kicad_sch_api_support": "native",
        "verified_surface": ["ComponentCollection.add"],
        "notes": "Component placement maps directly to ComponentCollection.add().",
    },
    "sch_add_wire": {
        "kicad_sch_api_support": "native",
        "verified_surface": ["Schematic.add_wire"],
        "notes": "Straight wire creation exists directly in the verified public API.",
    },
    "sch_add_label": {
        "kicad_sch_api_support": "native",
        "verified_surface": ["Schematic.add_label"],
        "notes": "Local label creation exists directly in the verified public API.",
    },
    "sch_add_power_symbol": {
        "kicad_sch_api_support": "wrapper_needed",
        "verified_surface": ["ComponentCollection.add"],
        "notes": (
            "Power symbols can be added as components, but hidden reference/value formatting "
            "needs a wrapper."
        ),
    },
    "sch_add_bus": {
        "kicad_sch_api_support": "wrapper_needed",
        "verified_surface": [],
        "notes": "Bus creation remains a compatibility wrapper around the KiCad file format.",
    },
    "sch_add_bus_wire_entry": {
        "kicad_sch_api_support": "wrapper_needed",
        "verified_surface": [],
        "notes": "Bus-entry creation remains a compatibility wrapper around the KiCad file format.",
    },
    "sch_add_no_connect": {
        "kicad_sch_api_support": "wrapper_needed",
        "verified_surface": [],
        "notes": "No-connect markers remain a compatibility wrapper around the KiCad file format.",
    },
    "sch_add_missing_junctions": {
        "kicad_sch_api_support": "wrapper_needed",
        "verified_surface": [],
        "notes": "Missing schematic junctions are repaired from file-level wire geometry.",
    },
    "sch_update_properties": {
        "kicad_sch_api_support": "wrapper_needed",
        "verified_surface": ["ComponentCollection.get", "Component.set_property"],
        "notes": (
            "Property updates are supported through component objects, but the current tool "
            "contract needs a wrapper."
        ),
    },
    "sch_build_circuit": {
        "kicad_sch_api_support": "wrapper_needed",
        "verified_surface": [
            "create_schematic",
            "ComponentCollection.add",
            "Schematic.add_wire",
            "Schematic.add_label",
        ],
        "notes": (
            "Circuit construction can be rebuilt on top of verified primitives, but "
            "auto-layout and formatting require a wrapper."
        ),
    },
    "sch_get_pin_positions": {
        "kicad_sch_api_support": "wrapper_needed",
        "verified_surface": [
            "Component.get_pin_position",
            "Schematic.list_component_pins",
            "get_symbol_info",
        ],
        "notes": (
            "Pin positions are available through component and symbol helpers, but the "
            "current library-oriented contract needs a wrapper."
        ),
    },
    "sch_check_power_flags": {
        "kicad_sch_api_support": "wrapper_needed",
        "verified_surface": [
            "Schematic.run_erc",
            "Schematic.validate",
            "Schematic.get_validation_summary",
        ],
        "notes": (
            "Power-flag analysis can be derived from ERC/validation output, but there is "
            "no direct one-shot helper."
        ),
    },
    "sch_annotate": {
        "kicad_sch_api_support": "wrapper_needed",
        "verified_surface": ["ComponentCollection.all", "ComponentCollection.get"],
        "notes": "Annotation remains a deterministic wrapper built on top of component metadata.",
    },
    "sch_reload": {
        "kicad_sch_api_support": "wrapper_needed",
        "verified_surface": ["KiCad IPC reload helper outside kicad-sch-api"],
        "notes": (
            "Reload is a KiCad IPC concern and will remain a wrapper around the active "
            "editor/session."
        ),
    },
    "sch_create_sheet": {
        "kicad_sch_api_support": "native",
        "verified_surface": ["Schematic.add_sheet", "create_schematic", "Schematic.save"],
        "notes": "Child sheet creation maps directly to the verified sheet manager helpers.",
    },
    "sch_add_hierarchical_label": {
        "kicad_sch_api_support": "wrapper_needed",
        "verified_surface": ["Schematic.add_hierarchical_label"],
        "notes": (
            "The public API can create hierarchical labels, but the wrapper preserves "
            "shape and formatting compatibility."
        ),
    },
    "sch_add_global_label": {
        "kicad_sch_api_support": "wrapper_needed",
        "verified_surface": ["Schematic.add_global_label"],
        "notes": (
            "The public API can create global labels, but the wrapper preserves shape "
            "and formatting compatibility."
        ),
    },
    "sch_list_sheets": {
        "kicad_sch_api_support": "native",
        "verified_surface": ["SheetManager.get_sheet_hierarchy", "SheetManager.get_sheet_by_name"],
        "notes": "Sheet listing is available directly from the verified sheet manager APIs.",
    },
    "sch_get_sheet_info": {
        "kicad_sch_api_support": "native",
        "verified_surface": ["SheetManager.get_sheet_by_name"],
        "notes": (
            "Detailed sheet metadata is available directly from "
            "SheetManager.get_sheet_by_name()."
        ),
    },
    "sch_route_wire_between_pins": {
        "kicad_sch_api_support": "wrapper_needed",
        "verified_surface": ["Schematic.add_wire_between_pins", "Component.get_pin_position"],
        "notes": (
            "Pin-to-pin routing is exposed in kicad-sch-api, but the wrapper keeps the "
            "current Manhattan-routing contract deterministic."
        ),
    },
    "sch_get_connectivity_graph": {
        "kicad_sch_api_support": "wrapper_needed",
        "verified_surface": [
            "Schematic.get_connected_pins",
            "Schematic.get_net_for_pin",
            "WireCollection.all",
        ],
        "notes": (
            "Connectivity summaries are composed from verified wire and component helpers "
            "to match the existing textual MCP surface."
        ),
    },
    "sch_trace_net": {
        "kicad_sch_api_support": "wrapper_needed",
        "verified_surface": [
            "Schematic.get_net_for_pin",
            "SheetManager.get_sheet_hierarchy",
            "SheetManager.get_sheet_by_name",
        ],
        "notes": (
            "Net tracing uses verified sheet metadata plus compatibility parsing to report "
            "cross-sheet matches."
        ),
    },
    "sch_auto_place_symbols": {
        "kicad_sch_api_support": "wrapper_needed",
        "verified_surface": ["ComponentCollection.get", "Component.move", "Schematic.save"],
        "notes": (
            "Auto-placement is implemented as a deterministic wrapper around component "
            "move helpers."
        ),
    },
}


class _SchematicBackendAdapter(Protocol):
    name: str
    capability_matrix: dict[str, SchematicCapabilityEntry]

    def parse_schematic_file(self, sch_file: Path) -> dict[str, Any]: ...

    def transactional_write(self, mutator: Callable[[str], str]) -> str: ...

    def update_symbol_property(self, reference: str, field: str, value: str) -> str: ...

    def reload_schematic(self) -> str: ...


class _PointLike(Protocol):
    x: float
    y: float


class _PlacedComponentLike(Protocol):
    lib_id: str
    reference: str
    value: str
    footprint: str
    position: _PointLike
    rotation: float
    _data: object

    def set_property(self, name: str, value: str) -> object: ...

    def move(self, x: float, y: float) -> object: ...


class _ComponentCollectionLike(Protocol):
    def all(self) -> Iterable[_PlacedComponentLike]: ...

    def get(self, reference: str) -> _PlacedComponentLike | None: ...


class _LabelLike(Protocol):
    text: str
    position: _PointLike
    rotation: float


class _LabelCollectionLike(Protocol):
    def all(self) -> Iterable[_LabelLike]: ...


class _WireLike(Protocol):
    start: _PointLike
    end: _PointLike


class _WireCollectionLike(Protocol):
    def all(self) -> Iterable[_WireLike]: ...


class _SheetManagerLike(Protocol):
    def get_sheet_hierarchy(self) -> dict[str, Any]: ...

    def get_sheet_by_name(self, name: str) -> dict[str, Any] | None: ...


class _LoadedSchematicLike(Protocol):
    components: _ComponentCollectionLike
    labels: _LabelCollectionLike
    wires: _WireCollectionLike
    sheets: _SheetManagerLike

    def add_sheet(
        self,
        name: str,
        filename: str,
        position: tuple[float, float],
        size: tuple[float, float],
        stroke_width: float | None = None,
        stroke_type: str = "solid",
        project_name: str | None = None,
        page_number: str | None = None,
        uuid: str | None = None,
    ) -> str: ...

    def save(self, file_path: Path | str | None = None, preserve_format: bool = True) -> object: ...

def _load_kicad_schematic(sch_file: Path) -> _LoadedSchematicLike:
    from kicad_sch_api import load_schematic

    return cast(_LoadedSchematicLike, load_schematic(str(sch_file)))


def _component_unit(component: _PlacedComponentLike) -> int:
    return int(getattr(getattr(component, "_data", None), "unit", 1) or 1)


def _component_to_symbol_dict(component: _PlacedComponentLike) -> dict[str, Any]:
    return {
        "lib_id": str(component.lib_id),
        "reference": str(component.reference),
        "value": str(component.value),
        "footprint": str(component.footprint or ""),
        "x": round(float(component.position.x), 4),
        "y": round(float(component.position.y), 4),
        "rotation": int(round(float(component.rotation))),
        "unit": _component_unit(component),
    }


def _api_labels(schematic: _LoadedSchematicLike) -> list[dict[str, Any]]:
    labels: list[dict[str, Any]] = []
    for label in cast(list[_LabelLike], list(schematic.labels.all())):
        labels.append(
            {
                "name": str(label.text),
                "x": round(float(label.position.x), 4),
                "y": round(float(label.position.y), 4),
                "rotation": int(round(float(getattr(label, "rotation", 0.0) or 0.0))),
            }
        )
    return labels


@dataclass(frozen=True)
class _KicadSchApiBackend:
    name: str = "kicad_sch_api"
    capability_matrix: dict[str, SchematicCapabilityEntry] = field(
        default_factory=lambda: deepcopy(SCHEMATIC_BACKEND_CAPABILITY_MATRIX)
    )

    def parse_schematic_file(self, sch_file: Path) -> dict[str, Any]:
        try:
            schematic = _load_kicad_schematic(sch_file)
        except Exception as exc:
            raise RuntimeError(
                f"Could not load schematic '{sch_file}' through kicad-sch-api."
            ) from exc

        compatibility = _read_schematic_compatibility_data(sch_file)

        try:
            symbols: list[dict[str, Any]] = []
            power_symbols: list[dict[str, Any]] = []
            for component in cast(list[_PlacedComponentLike], list(schematic.components.all())):
                parsed = _component_to_symbol_dict(component)
                if parsed["lib_id"].startswith("power:"):
                    power_symbols.append(parsed)
                else:
                    symbols.append(parsed)

            labels = compatibility["labels"]
            seen_labels = {
                (
                    label["name"],
                    round(float(label["x"]), 4),
                    round(float(label["y"]), 4),
                    int(label["rotation"]),
                )
                for label in labels
            }
            for label in _api_labels(schematic):
                key = (
                    label["name"],
                    round(float(label["x"]), 4),
                    round(float(label["y"]), 4),
                    int(label["rotation"]),
                )
                if key not in seen_labels:
                    labels.append(label)

            wires: list[dict[str, Any]] = []
            compatibility_wires = list(cast(list[dict[str, Any]], compatibility["wires"]))
            compatibility_lookup = {
                _wire_signature(wire["x1"], wire["y1"], wire["x2"], wire["y2"]): wire
                for wire in compatibility_wires
            }
            seen_wire_signatures: set[tuple[tuple[float, float], tuple[float, float]]] = set()
            for wire in cast(list[_WireLike], list(schematic.wires.all())):
                parsed_wire = {
                    "x1": round(float(wire.start.x), 4),
                    "y1": round(float(wire.start.y), 4),
                    "x2": round(float(wire.end.x), 4),
                    "y2": round(float(wire.end.y), 4),
                }
                signature = _wire_signature(
                    parsed_wire["x1"],
                    parsed_wire["y1"],
                    parsed_wire["x2"],
                    parsed_wire["y2"],
                )
                seen_wire_signatures.add(signature)
                compatibility_wire = compatibility_lookup.get(signature)
                if compatibility_wire is not None and compatibility_wire.get("uuid"):
                    parsed_wire["uuid"] = compatibility_wire["uuid"]
                wires.append(parsed_wire)

            for compat_wire in compatibility_wires:
                signature = _wire_signature(
                    compat_wire["x1"],
                    compat_wire["y1"],
                    compat_wire["x2"],
                    compat_wire["y2"],
                )
                if signature not in seen_wire_signatures:
                    wires.append(compat_wire)

            return {
                "uuid": compatibility["uuid"],
                "symbols": symbols,
                "power_symbols": power_symbols,
                "wires": wires,
                "labels": labels,
                "buses": compatibility["buses"],
            }
        except Exception as exc:
            logger.debug(
                "schematic_backend_parse_failed",
                schematic_file=str(sch_file),
                error=str(exc),
            )
            raise RuntimeError(f"Could not parse schematic '{sch_file}'.") from exc

    def transactional_write(self, mutator: Callable[[str], str]) -> str:
        return _transactional_write_to_schematic(mutator)

    def update_symbol_property(self, reference: str, field: str, value: str) -> str:
        payload = UpdatePropertiesInput(reference=reference, field=field, value=value)
        sch_file = _get_schematic_file()
        try:
            schematic = _load_kicad_schematic(sch_file)
            component = schematic.components.get(payload.reference)
            if component is None:
                return _update_symbol_property_text_fallback(
                    payload.reference,
                    payload.field,
                    payload.value,
                )

            normalized_field = payload.field.casefold()
            if normalized_field == "reference":
                component.reference = payload.value
            elif normalized_field == "value":
                component.value = payload.value
            elif normalized_field == "footprint":
                component.footprint = payload.value
            else:
                component.set_property(payload.field, payload.value)

            schematic.save(sch_file, preserve_format=True)
            return f"Updated {payload.reference}.{payload.field}."
        except Exception as exc:
            logger.debug(
                "schematic_backend_property_update_fallback",
                reference=payload.reference,
                field=payload.field,
                error=str(exc),
            )
            return _update_symbol_property_text_fallback(
                payload.reference,
                payload.field,
                payload.value,
            )

    def reload_schematic(self) -> str:
        return _reload_schematic_via_ipc()


_SCHEMATIC_BACKENDS: dict[str, _SchematicBackendAdapter] = {
    "kicad_sch_api": cast(_SchematicBackendAdapter, _KicadSchApiBackend()),
}
_DEFAULT_SCHEMATIC_BACKEND = "kicad_sch_api"


def get_schematic_backend() -> _SchematicBackendAdapter:
    """Return the currently active schematic backend adapter."""
    return _SCHEMATIC_BACKENDS[_DEFAULT_SCHEMATIC_BACKEND]


def new_uuid() -> str:
    """Create a KiCad UUID string."""
    return str(uuid.uuid4())


_STRING_PATTERN = r'"((?:\\.|[^"\\])*)"'
_FLOAT_PATTERN = r"-?\d+(?:\.\d+)?"


def _snap_schematic_coord(value: float) -> float:
    snapped = round(round(value / SCHEMATIC_GRID_MM) * SCHEMATIC_GRID_MM, 4)
    return 0.0 if abs(snapped) < SNAP_TOLERANCE_MM else snapped


def _snap_point(x: float, y: float, enabled: bool) -> tuple[float, float]:
    if not enabled:
        return x, y
    return _snap_schematic_coord(x), _snap_schematic_coord(y)


def _snap_line(
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    enabled: bool,
) -> tuple[float, float, float, float]:
    if not enabled:
        return x1, y1, x2, y2
    return (
        _snap_schematic_coord(x1),
        _snap_schematic_coord(y1),
        _snap_schematic_coord(x2),
        _snap_schematic_coord(y2),
    )


def _snap_notice(original: tuple[float, ...], snapped: tuple[float, ...]) -> str:
    if all(
        abs(before - after) <= SNAP_TOLERANCE_MM
        for before, after in zip(original, snapped, strict=True)
    ):
        return ""
    return f"Grid snap: {original} -> {snapped}"


def _fmt_mm(value: float) -> str:
    rounded = round(value, 4)
    if abs(rounded) < SNAP_TOLERANCE_MM:
        rounded = 0.0
    formatted = f"{rounded:.4f}".rstrip("0").rstrip(".")
    return formatted or "0"


def _auto_layout_point(index: int) -> tuple[float, float]:
    column = index % AUTO_LAYOUT_COLUMNS
    row = index // AUTO_LAYOUT_COLUMNS
    return (
        AUTO_LAYOUT_ORIGIN_X_MM + (column * AUTO_LAYOUT_COLUMN_SPACING_MM),
        AUTO_LAYOUT_ORIGIN_Y_MM + (row * AUTO_LAYOUT_ROW_SPACING_MM),
    )


# ---------------------------------------------------------------------------
# Spatial awareness helpers (v2.1.0)
# ---------------------------------------------------------------------------

# Approximate bounding box half-sizes for common symbol categories (mm).
# These are heuristic estimates; KiCad doesn't expose symbol extents via the
# file-level API, so we size conservatively.
_SYMBOL_HALF_W_MM = 10.16   # ~4 pins wide  (2 × 2.54 × 2)
_SYMBOL_HALF_H_MM = 7.62    # ~3 pins tall


@dataclass(frozen=True)
class BBox:
    """Axis-aligned schematic obstacle bounds in millimetres."""

    x_min: float
    y_min: float
    x_max: float
    y_max: float

    def padded(self, amount_mm: float) -> BBox:
        return BBox(
            self.x_min - amount_mm,
            self.y_min - amount_mm,
            self.x_max + amount_mm,
            self.y_max + amount_mm,
        )


# ---------------------------------------------------------------------------
# Footprint validation (v2.1.1)
# ---------------------------------------------------------------------------

# KiCad system footprint search paths (platform-ordered)
_KICAD_FP_SEARCH_PATHS: list[Path] = [
    Path("C:/Program Files/KiCad/10.0/share/kicad/footprints"),
    Path("C:/Program Files/KiCad/9.0/share/kicad/footprints"),
    Path("C:/Program Files/KiCad/8.0/share/kicad/footprints"),
    Path("/usr/share/kicad/footprints"),
    Path("/usr/local/share/kicad/footprints"),
    Path("/Applications/KiCad/KiCad.app/Contents/SharedSupport/footprints"),
]


def _fp_search_roots() -> list[Path]:
    """Return existing KiCad footprint roots (system + project custom)."""
    roots = [p for p in _KICAD_FP_SEARCH_PATHS if p.exists()]
    # Also check project-local .pretty dirs
    try:
        cfg = get_config()
        if cfg.project_dir:
            for pretty in cfg.project_dir.rglob("*.pretty"):
                if pretty.is_dir():
                    roots.append(pretty.parent)
    except Exception as exc:
        logger.debug("footprint_search_roots_failed", error=str(exc))
    return roots


def _validate_footprint(footprint: str) -> str | None:
    """Return a warning string if the footprint cannot be found in any known library.

    Returns None if the footprint is valid (or empty/not provided).
    Format expected: ``LibraryName:FootprintName``
    """
    if not footprint or ":" not in footprint:
        if footprint:
            return (
                f"Footprint '{footprint}' has invalid format — expected 'Library:Name'. "
                "Symbol was placed but footprint assignment may fail in KiCad."
            )
        return None

    lib, name = footprint.split(":", 1)
    roots = _fp_search_roots()
    if not roots:
        return None  # Can't validate without knowing the path — don't block

    for root in roots:
        candidate = root / f"{lib}.pretty" / f"{name}.kicad_mod"
        if candidate.exists():
            return None  # Found — valid

    # Not found anywhere; suggest closest alternative
    suggestions: list[str] = []
    for root in roots:
        lib_dir = root / f"{lib}.pretty"
        if lib_dir.exists():
            # Library exists but footprint name wrong — suggest similar names
            mods = list(lib_dir.glob("*.kicad_mod"))
            name_lower = name.lower()
            close = [m.stem for m in mods if name_lower in m.stem.lower()][:3]
            if close:
                suggestions = [f"{lib}:{s}" for s in close]
            break

    hint = f" Did you mean: {', '.join(suggestions)}?" if suggestions else ""
    return (
        f"WARNING: Footprint '{footprint}' not found in KiCad library.{hint} "
        "Symbol placed — fix footprint in KiCad Properties dialog."
    )


# ---------------------------------------------------------------------------
# Functional category classifier (v2.1.1)
# ---------------------------------------------------------------------------

# Zone layout — (start_col, start_row) for each functional group.
#
# A4 landscape = 297 × 210 mm.  Usable columns with origin=50.8 and
# spacing=25.4: (297 - 50.8 - 15 margin) / 25.4 ≈ 9.1 → max col 8.
# Usable rows: (210 - 50.8 - 15) / 17.78 ≈ 8.1 → max row 7.
# All zones start at col ≤ 6 so they (+ max 3 sub-cols) stay within col 8.
#
#   col →    0-2          3-5          6-8
#   row 0:   connectors   MCU          UI / LED / SW
#   row 3:   power IC     sensors/IC   protection
#   row 5:   power pass   passives     transistors / filter
#   row 7:   test points  ---          ---
_FUNCTIONAL_ZONES: dict[str, tuple[int, int]] = {
    "connector":    (0, 0),   # Left — connectors, headers
    "mcu":          (3, 0),   # Centre-left — main processor
    "ui":           (6, 0),   # Right — LED, buzzer, button, switch
    "power_ic":     (0, 3),   # Left-mid — LDO, buck, PMU
    "sensor":       (3, 3),   # Centre-mid — sensors
    "ic":           (3, 3),   # Generic IC — shares sensor zone
    "protection":   (6, 3),   # Right-mid — ESD, TVS, fuse, diode
    "power_pass":   (0, 5),   # Left-lower — bulk caps, ferrite, input
    "passive_cap":  (2, 5),   # Lower-centre-left — decoupling caps
    "passive_res":  (4, 5),   # Lower-centre — resistors
    "transistor":   (6, 5),   # Right-lower — MOSFET, BJT
    "filter":       (6, 6),   # Right-bottom — ferrite, LC filter
    "testpoint":    (0, 7),   # Bottom-left — test points
    "misc":         (5, 7),   # Bottom-right — anything else
}

# Maximum sub-columns per zone before wrapping to the next sub-row within it.
_ZONE_MAX_COLS = 3


def _classify_symbol(ref: str, value: str, lib_id: str) -> str:
    """Return a functional category string for a symbol."""
    prefix = "".join(c for c in ref if c.isalpha()).upper().rstrip("0123456789")
    lib_up = lib_id.upper()
    val_up = value.upper()

    # Connectors / headers
    if prefix in ("J", "CN", "P", "X", "SV"):
        return "connector"

    # Test points
    if prefix in ("TP", "TEST"):
        return "testpoint"

    # Switches / buttons
    if prefix in ("SW", "BTN", "BT", "S"):
        return "ui"

    # LEDs (RGB, indicator)
    if prefix in ("LED", "D_LED"):
        return "ui"

    # Buzzers
    if prefix in ("BZ", "SP", "LS"):
        return "ui"

    # Fuses / polyfuse
    if prefix in ("F", "FU"):
        return "protection"

    # Ferrite beads / inductors
    if prefix in ("FB", "L", "FL"):
        return "filter"

    # Capacitors
    if prefix == "C":
        return "passive_cap"

    # Resistors
    if prefix == "R":
        return "passive_res"

    # Transistors
    if prefix in ("Q", "T"):
        return "transistor"

    # Diodes — split by function
    if prefix == "D":
        if any(k in val_up for k in ("USBLC", "ESD", "TVS", "PRTR", "BAT", "SCHOTTKY")):
            return "protection"
        if any(k in val_up for k in ("1N4148", "LED")):
            return "protection"
        return "protection"

    # ICs — further classify
    if prefix == "U":
        if any(
            k in lib_up
            for k in ("ESP32", "STM32", "ATMEGA", "NRF5", "RP2", "PIC", "RF_MODULE")
        ):
            return "mcu"
        if any(
            k in lib_up
            for k in (
                "SENSOR",
                "ADXL",
                "BME",
                "BMP",
                "BMI",
                "MPU",
                "ICM",
                "LIS",
                "VEML",
                "OPT",
                "SPH",
                "ICS",
            )
        ):
            return "sensor"
        if any(
            k in lib_up
            for k in (
                "REGUL",
                "LDO",
                "BUCK",
                "BOOST",
                "AP2112",
                "AMS",
                "MIC55",
                "AP3",
                "TPS",
                "LM",
                "XC6",
            )
        ):
            return "power_ic"
        if any(k in val_up for k in ("LDO", "REGUL", "AP2112", "AMS1117", "LM317", "XC6")):
            return "power_ic"
        if any(k in lib_up for k in ("PROTECTION", "USBLC", "PRTR", "ESD")):
            return "protection"
        return "ic"

    return "misc"


def _estimate_occupied_cells(
    symbols: list[dict[str, Any]],
    cell_w: float = AUTO_LAYOUT_COLUMN_SPACING_MM,
    cell_h: float = AUTO_LAYOUT_ROW_SPACING_MM,
) -> set[tuple[int, int]]:
    """Return the set of grid cells already occupied by placed symbols.

    Each symbol is assumed to occupy a rectangle of cell_w × cell_h mm
    centred on its (x, y) position.  We mark the grid cell of the centre
    plus the four neighbouring cells as occupied to give a clearance buffer.
    """
    occupied: set[tuple[int, int]] = set()
    for sym in symbols:
        x = sym.get("x", sym.get("x_mm", 0.0))
        y = sym.get("y", sym.get("y_mm", 0.0))
        if x is None or y is None:
            continue
        col = int(round((float(x) - AUTO_LAYOUT_ORIGIN_X_MM) / cell_w))
        row = int(round((float(y) - AUTO_LAYOUT_ORIGIN_Y_MM) / cell_h))
        for dc in (-1, 0, 1):
            for dr in (-1, 0, 1):
                occupied.add((col + dc, row + dr))
    return occupied


def _sheet_usable_cols(
    paper: str = "A4",
    cell_w: float = AUTO_LAYOUT_COLUMN_SPACING_MM,
) -> int:
    """Return the max column index that fits inside the given paper size."""
    w, _ = PAPER_SIZES_MM.get(paper, PAPER_SIZES_MM["A4"])
    usable_w = w - AUTO_LAYOUT_ORIGIN_X_MM - _SHEET_MARGIN_MM
    return max(1, int(usable_w / cell_w))


def _sheet_usable_rows(
    paper: str = "A4",
    cell_h: float = AUTO_LAYOUT_ROW_SPACING_MM,
) -> int:
    """Return the max row index that fits inside the given paper size."""
    _, h = PAPER_SIZES_MM.get(paper, PAPER_SIZES_MM["A4"])
    usable_h = h - AUTO_LAYOUT_ORIGIN_Y_MM - _SHEET_MARGIN_MM
    return max(1, int(usable_h / cell_h))


def _read_sheet_paper(sch_file: Path) -> str:
    """Read the paper size keyword from a .kicad_sch file, defaulting to 'A4'."""
    try:
        text = sch_file.read_text(encoding="utf-8", errors="replace")
        m = re.search(r'\(paper\s+"([^"]+)"', text)
        if m:
            return m.group(1)
    except Exception as exc:
        logger.debug("sheet_paper_parse_failed", error=str(exc))
    return "A4"


def _symbol_bbox_bounds(symbol: dict[str, Any]) -> tuple[float, float, float, float]:
    """Estimate a symbol bounding box and widen it to include routed pin tips."""
    x = float(symbol.get("x", symbol.get("x_mm", 0.0)) or 0.0)
    y = float(symbol.get("y", symbol.get("y_mm", 0.0)) or 0.0)
    x_min = x - _SYMBOL_HALF_W_MM
    y_min = y - _SYMBOL_HALF_H_MM
    x_max = x + _SYMBOL_HALF_W_MM
    y_max = y + _SYMBOL_HALF_H_MM

    lib_id = str(symbol.get("lib_id", "") or "")
    if not lib_id:
        return x_min, y_min, x_max, y_max

    try:
        library, symbol_name = _split_lib_id(lib_id)
    except ValueError:
        return x_min, y_min, x_max, y_max

    try:
        rotation = int(round(float(symbol.get("rotation", 0.0) or 0.0)))
        unit = int(symbol.get("unit", 1) or 1)
    except (TypeError, ValueError):
        return x_min, y_min, x_max, y_max

    try:
        pins = get_pin_positions(
            library=library,
            symbol_name=symbol_name,
            sym_x=x,
            sym_y=y,
            rotation=rotation,
            unit=unit,
        )
    except (FileNotFoundError, OSError, ValueError) as exc:
        logger.debug("symbol_bbox_pin_lookup_failed", lib_id=lib_id, error=str(exc))
        return x_min, y_min, x_max, y_max
    if not pins:
        return x_min, y_min, x_max, y_max

    pin_xs = [point[0] for point in pins.values()]
    pin_ys = [point[1] for point in pins.values()]
    return (
        min(x_min, min(pin_xs)),
        min(y_min, min(pin_ys)),
        max(x_max, max(pin_xs)),
        max(y_max, max(pin_ys)),
    )


def _normalize_keepout_region(
    region: tuple[float, float, float, float],
) -> tuple[float, float, float, float]:
    x1, y1, x2, y2 = region
    return min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2)


def _keepout_occupied_cells(
    keepout_regions: list[tuple[float, float, float, float]],
    *,
    cell_w: float,
    cell_h: float,
) -> set[tuple[int, int]]:
    """Map rectangular keepouts to blocked grid cells for placement search."""
    blocked: set[tuple[int, int]] = set()
    for region in keepout_regions:
        x_min, y_min, x_max, y_max = _normalize_keepout_region(region)
        start_col = int(
            math.floor((x_min - _SYMBOL_HALF_W_MM - AUTO_LAYOUT_ORIGIN_X_MM) / cell_w)
        )
        end_col = int(
            math.ceil((x_max + _SYMBOL_HALF_W_MM - AUTO_LAYOUT_ORIGIN_X_MM) / cell_w)
        )
        start_row = int(
            math.floor((y_min - _SYMBOL_HALF_H_MM - AUTO_LAYOUT_ORIGIN_Y_MM) / cell_h)
        )
        end_row = int(
            math.ceil((y_max + _SYMBOL_HALF_H_MM - AUTO_LAYOUT_ORIGIN_Y_MM) / cell_h)
        )
        for col in range(start_col, end_col + 1):
            for row in range(start_row, end_row + 1):
                blocked.add((col, row))
    return blocked


def _next_free_cell(
    occupied: set[tuple[int, int]],
    cell_w: float = AUTO_LAYOUT_COLUMN_SPACING_MM,
    cell_h: float = AUTO_LAYOUT_ROW_SPACING_MM,
    start_col: int = 0,
    start_row: int = 0,
    max_cols: int | None = None,
    paper: str = "A4",
) -> tuple[float, float]:
    """Return the (x_mm, y_mm) of the next unoccupied grid cell.

    Scans row-major order starting at (start_col, start_row).
    Column count is clamped to the usable width of ``paper`` so symbols
    never overflow the sheet boundary.
    """
    if max_cols is None:
        max_cols = _sheet_usable_cols(paper, cell_w)

    col, row = start_col, start_row
    # Safety: if start_col is beyond the sheet, wrap it back
    if col >= max_cols:
        col = 0

    while True:
        if (col, row) not in occupied:
            occupied.add((col, row))
            x = AUTO_LAYOUT_ORIGIN_X_MM + col * cell_w
            y = AUTO_LAYOUT_ORIGIN_Y_MM + row * cell_h
            return x, y
        col += 1
        if col >= max_cols:
            col = 0
            row += 1


def _point_near_existing(
    x: float,
    y: float,
    existing: list[dict[str, Any]],
    min_dist_mm: float = _SYMBOL_HALF_W_MM,
) -> str | None:
    """Return a warning string if (x, y) is too close to any existing symbol, else None."""
    for sym in existing:
        sx = float(sym.get("x", sym.get("x_mm", 0.0)) or 0.0)
        sy = float(sym.get("y", sym.get("y_mm", 0.0)) or 0.0)
        dist = math.hypot(x - sx, y - sy)
        if dist < min_dist_mm:
            ref = sym.get("reference", "?")
            return (
                f"WARNING: coordinate ({x:.2f}, {y:.2f}) is {dist:.1f} mm from '{ref}' "
                f"at ({sx:.2f}, {sy:.2f}) — symbols may overlap. "
                f"Use sch_find_free_placement to get a safe coordinate."
            )
    return None


def _normalize_anchor_refs(anchor_ref: str | list[str] | None) -> list[str]:
    if anchor_ref is None:
        return []
    if isinstance(anchor_ref, str):
        refs = [anchor_ref]
    else:
        refs = list(anchor_ref)

    normalized: list[str] = []
    seen: set[str] = set()
    for ref in refs:
        cleaned = ref.strip()
        if cleaned and cleaned not in seen:
            normalized.append(cleaned)
            seen.add(cleaned)
    return normalized


def _functional_zone_origin(
    category: str,
    *,
    max_cols: int,
    max_rows: int,
    spacing_mm: float,
) -> tuple[int, int]:
    zone_col, zone_row = _FUNCTIONAL_ZONES.get(category, (5, 7))
    unique_cols = sorted({col for col, _ in _FUNCTIONAL_ZONES.values()})
    unique_rows = sorted({row for _, row in _FUNCTIONAL_ZONES.values()})
    extra_cols = max(0, math.ceil(spacing_mm / AUTO_LAYOUT_COLUMN_SPACING_MM) - 1)
    extra_rows = max(0, math.ceil(spacing_mm / AUTO_LAYOUT_ROW_SPACING_MM) - 1)
    zone_col += unique_cols.index(zone_col) * extra_cols
    zone_row += unique_rows.index(zone_row) * extra_rows
    return (
        min(zone_col, max(0, max_cols - _ZONE_MAX_COLS)),
        min(zone_row, max(0, max_rows - 1)),
    )


def _netlist_layout_point(index: int) -> tuple[float, float]:
    column = index % AUTO_LAYOUT_COLUMNS
    row = index // AUTO_LAYOUT_COLUMNS
    return (
        AUTO_LAYOUT_ORIGIN_X_MM + (column * NETLIST_LAYOUT_COLUMN_SPACING_MM),
        AUTO_LAYOUT_ORIGIN_Y_MM + (row * NETLIST_LAYOUT_ROW_SPACING_MM),
    )


def _coord_value(item: dict[str, Any], name: str) -> float | None:
    value = item.get(f"{name}_mm", item.get(name))
    return float(value) if value is not None else None


def _has_point(item: dict[str, Any]) -> bool:
    return _coord_value(item, "x") is not None and _coord_value(item, "y") is not None


def _set_point(item: dict[str, Any], x: float, y: float) -> None:
    item["x_mm"] = _snap_schematic_coord(x)
    item["y_mm"] = _snap_schematic_coord(y)
    item.setdefault("snap_to_grid", True)


def _net_name(net: dict[str, Any]) -> str:
    value = net.get("name", net.get("net", net.get("label", "")))
    return str(value)


def _is_power_net(name: str) -> bool:
    upper_name = name.upper()
    return upper_name in POWER_NET_NAMES or upper_name.startswith(("+", "-"))


def _normalize_net_endpoint(endpoint: object) -> dict[str, Any]:
    if isinstance(endpoint, str):
        for separator in (".", ":"):
            if separator in endpoint:
                reference, pin = endpoint.split(separator, 1)
                return {"reference": reference, "pin": pin}
        if _is_power_net(endpoint):
            return {"power": endpoint}
        return {"label": endpoint}
    if isinstance(endpoint, dict):
        return dict(endpoint)
    return {}


def _net_endpoints(net: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("endpoints", "connections", "pins", "nodes"):
        value = net.get(key)
        if isinstance(value, list):
            return [_normalize_net_endpoint(item) for item in value]

    from_ref = net.get("from_ref", net.get("from_reference"))
    to_ref = net.get("to_ref", net.get("to_reference"))
    if from_ref is not None and to_ref is not None:
        return [
            {"reference": from_ref, "pin": net.get("from_pin")},
            {"reference": to_ref, "pin": net.get("to_pin")},
        ]
    return []


def _endpoint_reference(endpoint: dict[str, Any]) -> str | None:
    value = endpoint.get("reference", endpoint.get("ref", endpoint.get("symbol")))
    return str(value) if value is not None else None


def _endpoint_pin(endpoint: dict[str, Any]) -> str | None:
    value = endpoint.get(
        "pin",
        endpoint.get(
            "pin_number",
            endpoint.get("number", endpoint.get("pin_name", endpoint.get("pad"))),
        ),
    )
    return str(value) if value is not None else None


def _endpoint_power(endpoint: dict[str, Any]) -> str | None:
    value = endpoint.get("power", endpoint.get("power_symbol", endpoint.get("rail")))
    if value is None and endpoint.get("type") == "power":
        value = endpoint.get("name")
    return str(value) if value is not None else None


def _endpoint_label(endpoint: dict[str, Any]) -> str | None:
    value = endpoint.get("label", endpoint.get("net_label"))
    if value is None and endpoint.get("type") == "label":
        value = endpoint.get("name")
    return str(value) if value is not None else None


def _refs_for_net(net: dict[str, Any], known_refs: set[str]) -> list[str]:
    refs: list[str] = []
    for endpoint in _net_endpoints(net):
        reference = _endpoint_reference(endpoint)
        if reference in known_refs and reference not in refs:
            refs.append(reference)
    return refs


def _order_refs_by_connectivity(refs: list[str], nets: list[dict[str, Any]]) -> list[str]:
    input_order = {reference: index for index, reference in enumerate(refs)}
    known_refs = set(refs)
    adjacency: dict[str, set[str]] = {reference: set() for reference in refs}
    for net in nets:
        net_refs = _refs_for_net(net, known_refs)
        for index, reference in enumerate(net_refs):
            for connected in net_refs[index + 1 :]:
                adjacency[reference].add(connected)
                adjacency[connected].add(reference)

    ordered: list[str] = []
    unvisited = set(refs)
    while unvisited:
        leaves = [reference for reference in unvisited if len(adjacency[reference]) <= 1]
        if leaves:
            start = min(leaves, key=lambda reference: input_order[reference])
        else:
            start = max(
                unvisited,
                key=lambda reference: (len(adjacency[reference]), -input_order[reference]),
            )

        queue = [start]
        unvisited.remove(start)
        for reference in queue:
            ordered.append(reference)
            neighbors = sorted(adjacency[reference] & unvisited, key=lambda item: input_order[item])
            for neighbor in neighbors:
                unvisited.remove(neighbor)
                queue.append(neighbor)
    return ordered


def _average_position(
    refs: list[str],
    positions: dict[str, tuple[float, float]],
) -> tuple[float, float] | None:
    points = [positions[reference] for reference in refs if reference in positions]
    if not points:
        return None
    return (
        sum(point[0] for point in points) / len(points),
        sum(point[1] for point in points) / len(points),
    )


def _ensure_netlist_terminals(
    power_symbols: list[dict[str, Any]],
    labels: list[dict[str, Any]],
    nets: list[dict[str, Any]],
) -> None:
    existing_powers = {str(item.get("name", "")).upper() for item in power_symbols}
    existing_labels = {str(item.get("name", "")) for item in labels}
    for net in nets:
        name = _net_name(net)
        if not name:
            continue
        endpoints = _net_endpoints(net)
        has_power_endpoint = any(_endpoint_power(endpoint) for endpoint in endpoints)
        has_label_endpoint = any(_endpoint_label(endpoint) for endpoint in endpoints)
        if _is_power_net(name):
            if name.upper() not in existing_powers and not has_power_endpoint:
                power_symbols.append({"name": name})
                existing_powers.add(name.upper())
        elif name not in existing_labels and not has_label_endpoint:
            labels.append({"name": name})
            existing_labels.add(name)


def _apply_netlist_auto_layout(
    symbols: list[dict[str, Any]],
    power_symbols: list[dict[str, Any]],
    labels: list[dict[str, Any]],
    nets: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    laid_out_symbols = [dict(item) for item in symbols]
    laid_out_powers = [dict(item) for item in power_symbols]
    laid_out_labels = [dict(item) for item in labels]
    _ensure_netlist_terminals(laid_out_powers, laid_out_labels, nets)

    refs = [str(symbol["reference"]) for symbol in laid_out_symbols if symbol.get("reference")]
    ordered_refs = _order_refs_by_connectivity(refs, nets)

    # Use occupancy grid to avoid symbol collisions in netlist layout too.
    netlist_occupied: set[tuple[int, int]] = set()
    # Pre-fill from symbols that already have explicit positions.
    for symbol in laid_out_symbols:
        if _has_point(symbol):
            sx = _coord_value(symbol, "x") or 0.0
            sy = _coord_value(symbol, "y") or 0.0
            col = int(round((sx - AUTO_LAYOUT_ORIGIN_X_MM) / NETLIST_LAYOUT_COLUMN_SPACING_MM))
            row = int(round((sy - AUTO_LAYOUT_ORIGIN_Y_MM) / NETLIST_LAYOUT_ROW_SPACING_MM))
            netlist_occupied.add((col, row))

    generated_positions: dict[str, tuple[float, float]] = {}
    for reference in ordered_refs:
        x, y = _next_free_cell(
            netlist_occupied,
            cell_w=NETLIST_LAYOUT_COLUMN_SPACING_MM,
            cell_h=NETLIST_LAYOUT_ROW_SPACING_MM,
        )
        generated_positions[reference] = (x, y)

    symbol_positions: dict[str, tuple[float, float]] = {}
    for symbol in laid_out_symbols:
        reference = str(symbol.get("reference", ""))
        if not _has_point(symbol):
            if reference in generated_positions:
                x, y = generated_positions[reference]
            else:
                x, y = _next_free_cell(
                    netlist_occupied,
                    cell_w=NETLIST_LAYOUT_COLUMN_SPACING_MM,
                    cell_h=NETLIST_LAYOUT_ROW_SPACING_MM,
                )
            _set_point(symbol, x, y)
        point = (_coord_value(symbol, "x"), _coord_value(symbol, "y"))
        if point[0] is not None and point[1] is not None and reference:
            symbol_positions[reference] = (point[0], point[1])

    known_refs = set(symbol_positions)
    for index, power_symbol in enumerate(laid_out_powers):
        if _has_point(power_symbol):
            continue
        name = str(power_symbol.get("name", ""))
        power_connected_refs: list[str] = []
        for net in nets:
            net_name = _net_name(net)
            endpoints = _net_endpoints(net)
            if net_name.upper() == name.upper() or any(
                (power := _endpoint_power(endpoint)) and power.upper() == name.upper()
                for endpoint in endpoints
            ):
                power_connected_refs.extend(_refs_for_net(net, known_refs))
        center = _average_position(power_connected_refs, symbol_positions)
        if center is None:
            x, y = _netlist_layout_point(index)
        else:
            x = center[0]
            y_values = [
                symbol_positions[reference][1]
                for reference in power_connected_refs
                if reference in symbol_positions
            ]
            y = (
                max(y_values) + NETLIST_POWER_OFFSET_MM
                if name.upper().startswith("GND")
                else min(y_values) - NETLIST_POWER_OFFSET_MM
            )
        _set_point(power_symbol, x, y)

    for index, label in enumerate(laid_out_labels):
        if _has_point(label):
            continue
        name = str(label.get("name", ""))
        label_connected_refs: list[str] = []
        for net in nets:
            if _net_name(net) == name:
                label_connected_refs.extend(_refs_for_net(net, known_refs))
        center = _average_position(label_connected_refs, symbol_positions)
        if center is None:
            x, y = _netlist_layout_point(index)
            y += NETLIST_LABEL_OFFSET_MM
        else:
            x = center[0]
            y = center[1] + NETLIST_LABEL_OFFSET_MM
        _set_point(label, x, y)

    return laid_out_symbols, laid_out_powers, laid_out_labels


def _apply_basic_auto_layout(
    symbols: list[dict[str, Any]],
    power_symbols: list[dict[str, Any]],
    labels: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    laid_out_symbols = [dict(item) for item in symbols]
    laid_out_powers = [dict(item) for item in power_symbols]
    laid_out_labels = [dict(item) for item in labels]

    # Use occupancy grid so every symbol gets a unique, non-overlapping slot.
    occupied: set[tuple[int, int]] = set()

    for symbol in laid_out_symbols:
        x, y = _next_free_cell(occupied)
        symbol["x_mm"] = x
        symbol["y_mm"] = y
        symbol.setdefault("snap_to_grid", True)

    symbol_rows = max(1, math.ceil(max(len(laid_out_symbols), 1) / AUTO_LAYOUT_COLUMNS))
    gnd_row = symbol_rows
    positive_row = -1  # above origin row

    pwr_occupied_gnd: set[tuple[int, int]] = set()
    pwr_occupied_pos: set[tuple[int, int]] = set()

    for power_symbol in laid_out_powers:
        name = str(power_symbol.get("name", "")).upper()
        if name.startswith("GND"):
            x, y = _next_free_cell(pwr_occupied_gnd, start_row=gnd_row)
        else:
            x, y = _next_free_cell(pwr_occupied_pos, start_row=positive_row)
        power_symbol["x_mm"] = x
        power_symbol["y_mm"] = y
        power_symbol.setdefault("snap_to_grid", True)

    label_row = gnd_row + 1
    lbl_occupied: set[tuple[int, int]] = set()
    for label in laid_out_labels:
        x, y = _next_free_cell(lbl_occupied, start_row=label_row)
        label["x_mm"] = x
        label["y_mm"] = y
        label.setdefault("snap_to_grid", True)

    return laid_out_symbols, laid_out_powers, laid_out_labels


def _read_schematic_compatibility_data(sch_file: Path) -> dict[str, Any]:
    """Read schematic data that kicad-sch-api 0.5.x does not yet surface directly."""
    content = sch_file.read_text(encoding="utf-8", errors="ignore")
    return {
        "uuid": _extract_uuid(content),
        "wires": _extract_wires(content),
        "labels": _extract_labels(content),
        "buses": _extract_buses(content),
    }


def parse_schematic_file(sch_file: Path) -> dict[str, Any]:
    """Parse a schematic file through the active backend adapter."""
    return get_schematic_backend().parse_schematic_file(sch_file)


def _extract_uuid(content: str) -> str:
    match = re.search(r'\(kicad_sch[^(]*\(uuid\s+"([^"]+)"', content)
    return match.group(1) if match else ""


def _coord_pair_key(x: float, y: float) -> tuple[float, float]:
    return round(float(x), 4), round(float(y), 4)


def _wire_signature(
    x1: float,
    y1: float,
    x2: float,
    y2: float,
) -> tuple[tuple[float, float], tuple[float, float]]:
    start = _coord_pair_key(x1, y1)
    end = _coord_pair_key(x2, y2)
    return (start, end) if start <= end else (end, start)


def _parse_symbol_block(block: str) -> dict[str, Any] | None:
    lib_id_match = re.search(rf"\(lib_id\s+{_STRING_PATTERN}\)", block)
    if lib_id_match is None:
        return None
    at_match = re.search(r"\(at\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\)", block)
    unit_match = re.search(r"\(unit\s+(\d+)\)", block)
    ref_match = re.search(rf'\(property\s+"Reference"\s+{_STRING_PATTERN}', block)
    value_match = re.search(rf'\(property\s+"Value"\s+{_STRING_PATTERN}', block)
    footprint_match = re.search(rf'\(property\s+"Footprint"\s+{_STRING_PATTERN}', block)
    return {
        "lib_id": _unescape_sexpr_string(lib_id_match.group(1)),
        "reference": _unescape_sexpr_string(ref_match.group(1)) if ref_match else "?",
        "value": _unescape_sexpr_string(value_match.group(1)) if value_match else "?",
        "footprint": _unescape_sexpr_string(footprint_match.group(1)) if footprint_match else "",
        "x": float(at_match.group(1)) if at_match else 0.0,
        "y": float(at_match.group(2)) if at_match else 0.0,
        "rotation": int(round(float(at_match.group(3)))) if at_match else 0,
        "unit": int(unit_match.group(1)) if unit_match else 1,
    }


def _extract_buses(content: str) -> list[dict[str, float]]:
    buses: list[dict[str, float]] = []
    for match in re.finditer(
        r"\(bus\s+\(pts\s+\(xy\s+([-\d.]+)\s+([-\d.]+)\)\s+\(xy\s+([-\d.]+)\s+([-\d.]+)\)\)",
        content,
    ):
        buses.append(
            {
                "x1": float(match.group(1)),
                "y1": float(match.group(2)),
                "x2": float(match.group(3)),
                "y2": float(match.group(4)),
            }
        )
    return buses


def _extract_wires(content: str) -> list[dict[str, Any]]:
    wires: list[dict[str, Any]] = []
    cursor = 0
    while cursor < len(content):
        if content[cursor:].startswith("(wire"):
            block, length = _extract_block(content, cursor)
            if block:
                pts_match = re.search(
                    (
                        r"\(pts\s+\(xy\s+([-\d.]+)\s+([-\d.]+)\)\s+"
                        r"\(xy\s+([-\d.]+)\s+([-\d.]+)\)\s*\)"
                    ),
                    block,
                )
                if pts_match is not None:
                    wire_record: dict[str, Any] = {
                        "x1": float(pts_match.group(1)),
                        "y1": float(pts_match.group(2)),
                        "x2": float(pts_match.group(3)),
                        "y2": float(pts_match.group(4)),
                    }
                    uuid_match = re.search(r'\(uuid\s+"([^"]+)"\)', block)
                    if uuid_match is not None:
                        wire_record["uuid"] = uuid_match.group(1)
                    wires.append(wire_record)
                cursor += length
                continue
        cursor += 1
    return wires


def _wire_segments_from_content(content: str) -> list[tuple[float, float, float, float]]:
    return [
        (float(wire["x1"]), float(wire["y1"]), float(wire["x2"]), float(wire["y2"]))
        for wire in _extract_wires(content)
    ]


def _get_symbol_bboxes(sexpr_content: str) -> list[BBox]:
    symbols: list[dict[str, Any]] = []
    cursor = 0
    while cursor < len(sexpr_content):
        if sexpr_content[cursor:].startswith("(symbol"):
            block, length = _extract_block(sexpr_content, cursor)
            if block:
                parsed = _parse_symbol_block(block)
                if parsed is not None:
                    symbols.append(parsed)
                cursor += length
                continue
        cursor += 1
    return [BBox(*_symbol_bbox_bounds(symbol)) for symbol in symbols]


def _remove_wire_blocks(content: str) -> str:
    pieces: list[str] = []
    cursor = 0
    last = 0
    while cursor < len(content):
        if content[cursor:].startswith("(wire"):
            block, length = _extract_block(content, cursor)
            if block and _parse_wire_block(block) is not None:
                pieces.append(content[last:cursor])
                cursor += length
                last = cursor
                continue
        cursor += 1
    pieces.append(content[last:])
    return "".join(pieces)


def _normalize_schematic_wire_connectivity(content: str) -> str:
    segments = _deduplicate_segments(_wire_segments_from_content(content))
    if not segments:
        return content
    updated = _remove_wire_blocks(content)
    for segment in segments:
        updated = _append_before_sheet_instances(updated, wire_block(*segment))
    return _insert_junctions_for_batch(updated, _detect_t_intersections(segments))


def _extract_labels(content: str) -> list[dict[str, Any]]:
    labels: list[dict[str, Any]] = []
    for match in re.finditer(
        rf"\((?:label|global_label|hierarchical_label)\s+{_STRING_PATTERN}\s+"
        r"(?:\(shape\s+\w+\)\s+)?\(at\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\)",
        content,
    ):
        labels.append(
            {
                "name": _unescape_sexpr_string(match.group(1)),
                "x": float(match.group(2)),
                "y": float(match.group(3)),
                "rotation": int(round(float(match.group(4)))),
            }
        )
    return labels


def _get_schematic_file() -> Path:
    cfg = get_config()
    if cfg.sch_file is None or not cfg.sch_file.exists():
        raise ValueError(
            "No schematic file is configured. Call kicad_set_project() or set KICAD_MCP_SCH_FILE."
        )
    return cfg.sch_file


def run_auto_annotate(start_number: int = 1, order: str = "alpha") -> str:
    """Module-level annotation runner — callable from project_auto_fix_loop.

    Renumbers all schematic references sequentially without requiring an MCP
    tool invocation.  Returns a human-readable summary string.
    """
    from ..models.schematic import AnnotateInput

    sch_file = _get_schematic_file()
    payload = AnnotateInput(start_number=start_number, order=order)
    data = parse_schematic_file(sch_file)
    symbols = list(data["symbols"])
    if payload.order == "sheet":
        symbols.sort(key=lambda item: (item["y"], item["x"]))
    else:
        symbols.sort(key=lambda item: item["reference"])

    counters: dict[str, int] = {}
    updates: list[tuple[str, str]] = []
    for symbol in symbols:
        prefix_match = re.match(r"([A-Za-z#]+)", symbol["reference"])
        prefix = prefix_match.group(1) if prefix_match else "U"
        counters.setdefault(prefix, payload.start_number)
        new_reference = f"{prefix}{counters[prefix]}"
        counters[prefix] += 1
        updates.append((symbol["reference"], new_reference))

    def mutator(current: str) -> str:
        updated = current
        for old_ref, new_ref in updates:
            updated = updated.replace(
                f'(property "Reference" "{old_ref}"',
                f'(property "Reference" "{new_ref}"',
                1,
            )
        return updated

    transactional_write(mutator)
    return f"Auto-annotated {len(updates)} symbol(s)."


def run_auto_add_missing_junctions() -> str:
    """Module-level missing-junction fixer for project_auto_fix_loop."""
    sch_file = _get_schematic_file()
    before = sch_file.read_text(encoding="utf-8", errors="ignore")
    before_count = len(_existing_junction_points(before))
    transactional_write(
        lambda current: _insert_junctions_for_batch(
            current,
            _detect_t_intersections(_deduplicate_segments(_wire_segments_from_content(current))),
        )
    )
    after = sch_file.read_text(encoding="utf-8", errors="ignore")
    inserted = max(0, len(_existing_junction_points(after)) - before_count)
    return f"Inserted {inserted} missing junction(s)."


def _get_symbol_library_dir() -> Path:
    cfg = get_config()
    if cfg.symbol_library_dir is None or not cfg.symbol_library_dir.exists():
        raise FileNotFoundError("No KiCad symbol library directory is configured.")
    return cfg.symbol_library_dir


def rotate_point(x: float, y: float, angle_deg: float) -> tuple[float, float]:
    """Rotate a point around the origin."""
    radians = math.radians(angle_deg)
    cos_a = math.cos(radians)
    sin_a = math.sin(radians)
    return (round(x * cos_a - y * sin_a, 4), round(x * sin_a + y * cos_a, 4))


def load_lib_symbol(library: str, symbol_name: str) -> str | None:
    """Load a symbol definition from a KiCad symbol library."""
    sym_file = _get_symbol_library_dir() / f"{library}.kicad_sym"
    if not sym_file.exists():
        return None

    content = sym_file.read_text(encoding="utf-8", errors="ignore")
    blocks = _collect_symbol_blocks(content, symbol_name)
    if not blocks:
        return None

    rendered_blocks = blocks[:-1]
    rendered_blocks.append(
        blocks[-1].replace(f'(symbol "{symbol_name}"', f'(symbol "{library}:{symbol_name}"', 1)
    )
    return "\n".join(rendered_blocks)


def _find_symbol_block(content: str, symbol_name: str) -> str | None:
    """Extract a single symbol block from a KiCad symbol library file."""
    start_marker = f'(symbol "{symbol_name}"'
    start = content.find(start_marker)
    if start == -1:
        return None
    block, _ = _extract_block(content, start)
    return block or None


def _find_symbol_extends(block: str) -> str | None:
    match = re.search(r'\(extends\s+"([^"]+)"\)', block)
    return match.group(1) if match else None


def _collect_symbol_blocks(
    content: str,
    symbol_name: str,
    visited: set[str] | None = None,
) -> list[str]:
    if visited is None:
        visited = set()
    if symbol_name in visited:
        return []
    visited.add(symbol_name)

    block = _find_symbol_block(content, symbol_name)
    if block is None:
        return []

    parent_name = _find_symbol_extends(block)
    if parent_name is None:
        return [block]
    return [*_collect_symbol_blocks(content, parent_name, visited), block]


def _symbol_block_name(block: str) -> str | None:
    match = re.match(r'\(symbol\s+"([^"]+)"', block.lstrip())
    return match.group(1) if match else None


def _extract_child_symbol_blocks(block: str) -> list[tuple[str, str]]:
    children: list[tuple[str, str]] = []
    depth = 0
    in_string = False
    escaped = False
    cursor = 0
    while cursor < len(block):
        char = block[cursor]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            cursor += 1
            continue
        if char == '"':
            in_string = True
            cursor += 1
            continue
        if char == "(":
            if depth == 1 and block.startswith('(symbol "', cursor):
                child_block, length = _extract_block(block, cursor)
                child_name = _symbol_block_name(child_block)
                if child_block and child_name is not None:
                    children.append((child_name, child_block))
                cursor += max(length, 1)
                continue
            depth += 1
        elif char == ")":
            depth -= 1
        cursor += 1
    return children


def _strip_child_symbol_blocks(block: str) -> str:
    stripped = block
    for _, child_block in _extract_child_symbol_blocks(block):
        stripped = stripped.replace(child_block, "")
    return stripped


def _extract_pin_definitions(block: str) -> dict[str, tuple[float, float]]:
    return {
        record["number"]: (float(record["x"]), float(record["y"]))
        for record in _extract_pin_records(block)
    }


def _extract_pin_records(block: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for match in re.finditer(
        r'\(pin\s+\w+\s+\w+\s+\(at\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\)\s+\(length\s+[-\d.]+\).*?\(name\s+"([^"]*)"\).*?\(number\s+"([^"]+)"',
        block,
        re.DOTALL,
    ):
        records.append(
            {
                "x": float(match.group(1)),
                "y": float(match.group(2)),
                "name": match.group(4),
                "number": match.group(5),
            }
        )
    return records


def _normalize_pin_alias(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


def _merge_pin_alias(
    aliases: dict[str, tuple[float, float]],
    conflicts: set[str],
    alias: str,
    point: tuple[float, float],
) -> None:
    if not alias:
        return
    existing = aliases.get(alias)
    if existing is None:
        aliases[alias] = point
        return
    if existing != point:
        conflicts.add(alias)


def _pin_alias_positions(
    block: str,
    sym_x: float,
    sym_y: float,
    rotation: int,
) -> dict[str, tuple[float, float]]:
    aliases: dict[str, tuple[float, float]] = {}
    conflicts: set[str] = set()
    for record in _extract_pin_records(block):
        rx, ry = rotate_point(float(record["x"]), -float(record["y"]), rotation)
        point = (round(sym_x + rx, 4), round(sym_y - ry, 4))
        number = str(record["number"])
        name = str(record["name"])
        for alias in {
            number,
            name,
            number.casefold(),
            name.casefold(),
            _normalize_pin_alias(number),
            _normalize_pin_alias(name),
        }:
            _merge_pin_alias(aliases, conflicts, alias, point)
    for alias in conflicts:
        aliases.pop(alias, None)
    return aliases


def _available_units_from_blocks(blocks: list[str]) -> set[int]:
    units: set[int] = set()
    has_direct_pins = False
    for block in blocks:
        direct_pins = _extract_pin_definitions(_strip_child_symbol_blocks(block))
        has_direct_pins = has_direct_pins or bool(direct_pins)
        block_name = _symbol_block_name(block)
        if block_name is None:
            continue
        prefix = f"{block_name}_"
        for child_name, _ in _extract_child_symbol_blocks(block):
            if not child_name.startswith(prefix):
                continue
            unit_str, _, _ = child_name[len(prefix) :].partition("_")
            if unit_str.isdigit() and int(unit_str) >= 1:
                units.add(int(unit_str))
    if not units and has_direct_pins:
        units.add(1)
    return units


def get_pin_positions(
    library: str,
    symbol_name: str,
    sym_x: float,
    sym_y: float,
    rotation: int = 0,
    unit: int = 1,
) -> dict[str, tuple[float, float]]:
    """Calculate absolute pin tip positions for a symbol placement."""
    sym_file = _get_symbol_library_dir() / f"{library}.kicad_sym"
    if not sym_file.exists():
        return {}

    content = sym_file.read_text(encoding="utf-8", errors="ignore")
    blocks = _collect_symbol_blocks(content, symbol_name)
    if not blocks:
        return {}
    available_units = _available_units_from_blocks(blocks)
    if available_units and unit not in available_units:
        return {}

    pins: dict[str, tuple[float, float]] = {}
    for block in blocks:
        direct_pins = _extract_pin_definitions(_strip_child_symbol_blocks(block))
        for pin_number, (px, py) in direct_pins.items():
            rx, ry = rotate_point(px, -py, rotation)
            pins[pin_number] = (round(sym_x + rx, 4), round(sym_y - ry, 4))

        block_name = _symbol_block_name(block)
        if block_name is None:
            continue
        unit_prefix = f"{block_name}_{unit}_"
        for child_name, child_block in _extract_child_symbol_blocks(block):
            if not child_name.startswith(unit_prefix):
                continue
            for pin_number, (px, py) in _extract_pin_definitions(child_block).items():
                # KiCad's pin (at x y angle) coordinate is the electrical connection point.
                rx, ry = rotate_point(px, -py, rotation)
                pins[pin_number] = (round(sym_x + rx, 4), round(sym_y - ry, 4))
    return pins


def get_pin_alias_positions(
    library: str,
    symbol_name: str,
    sym_x: float,
    sym_y: float,
    rotation: int = 0,
    unit: int = 1,
) -> dict[str, tuple[float, float]]:
    """Return a lookup for pin numbers, names, and normalized aliases."""
    sym_file = _get_symbol_library_dir() / f"{library}.kicad_sym"
    if not sym_file.exists():
        return {}

    content = sym_file.read_text(encoding="utf-8", errors="ignore")
    blocks = _collect_symbol_blocks(content, symbol_name)
    if not blocks:
        return {}
    available_units = _available_units_from_blocks(blocks)
    if available_units and unit not in available_units:
        return {}

    aliases: dict[str, tuple[float, float]] = {}
    conflicts: set[str] = set()
    for block in blocks:
        for alias, point in _pin_alias_positions(
            _strip_child_symbol_blocks(block),
            sym_x,
            sym_y,
            rotation,
        ).items():
            _merge_pin_alias(aliases, conflicts, alias, point)

        block_name = _symbol_block_name(block)
        if block_name is None:
            continue
        unit_prefix = f"{block_name}_{unit}_"
        for child_name, child_block in _extract_child_symbol_blocks(block):
            if not child_name.startswith(unit_prefix):
                continue
            for alias, point in _pin_alias_positions(
                child_block,
                sym_x,
                sym_y,
                rotation,
            ).items():
                _merge_pin_alias(aliases, conflicts, alias, point)

    for alias in conflicts:
        aliases.pop(alias, None)
    return aliases


def get_symbol_available_units(library: str, symbol_name: str) -> set[int]:
    """Return supported symbol units from the KiCad library."""
    sym_file = _get_symbol_library_dir() / f"{library}.kicad_sym"
    if not sym_file.exists():
        return set()

    content = sym_file.read_text(encoding="utf-8", errors="ignore")
    blocks = _collect_symbol_blocks(content, symbol_name)
    if not blocks:
        return set()
    return _available_units_from_blocks(blocks)


def _format_available_units(units: set[int]) -> str:
    return ", ".join(str(unit) for unit in sorted(units)) if units else "unknown"


def _manhattan_segments(
    start: tuple[float, float],
    end: tuple[float, float],
    snap_to_grid: bool,
) -> list[tuple[float, float, float, float]]:
    x1, y1, x2, y2 = _snap_line(start[0], start[1], end[0], end[1], snap_to_grid)
    if abs(x1 - x2) <= SNAP_TOLERANCE_MM and abs(y1 - y2) <= SNAP_TOLERANCE_MM:
        return []
    if abs(x1 - x2) <= SNAP_TOLERANCE_MM or abs(y1 - y2) <= SNAP_TOLERANCE_MM:
        return [(x1, y1, x2, y2)]
    return [(x1, y1, x2, y1), (x2, y1, x2, y2)]


def _segment_key(
    segment: tuple[float, float, float, float],
) -> tuple[tuple[float, float], tuple[float, float]]:
    start = (round(segment[0], 4), round(segment[1], 4))
    end = (round(segment[2], 4), round(segment[3], 4))
    return (start, end) if start <= end else (end, start)


def _point_on_segment_midpoint(
    point: tuple[float, float],
    segment: tuple[float, float, float, float],
) -> bool:
    px, py = point
    x1, y1, x2, y2 = segment
    endpoints = {_coord_pair_key(x1, y1), _coord_pair_key(x2, y2)}
    if _coord_pair_key(px, py) in endpoints:
        return False
    if abs(x1 - x2) <= SNAP_TOLERANCE_MM:
        return (
            abs(px - x1) <= SNAP_TOLERANCE_MM
            and min(y1, y2) + SNAP_TOLERANCE_MM < py < max(y1, y2) - SNAP_TOLERANCE_MM
        )
    if abs(y1 - y2) <= SNAP_TOLERANCE_MM:
        return (
            abs(py - y1) <= SNAP_TOLERANCE_MM
            and min(x1, x2) + SNAP_TOLERANCE_MM < px < max(x1, x2) - SNAP_TOLERANCE_MM
        )
    return False


def _detect_t_intersections(
    wires: list[tuple[float, float, float, float]],
) -> list[tuple[float, float]]:
    """Return wire endpoints that land on another wire's interior."""
    junctions: set[tuple[float, float]] = set()
    for index, segment in enumerate(wires):
        endpoints = ((segment[0], segment[1]), (segment[2], segment[3]))
        for point in endpoints:
            if any(
                other_index != index and _point_on_segment_midpoint(point, other)
                for other_index, other in enumerate(wires)
            ):
                junctions.add(_coord_pair_key(point[0], point[1]))
    return sorted(junctions)


def _deduplicate_segments(
    segments: list[tuple[float, float, float, float]],
) -> list[tuple[float, float, float, float]]:
    """Remove duplicate wire segments and merge collinear touching runs."""
    unique: dict[
        tuple[tuple[float, float], tuple[float, float]],
        tuple[float, float, float, float],
    ] = {}
    for segment in segments:
        x1, y1, x2, y2 = segment
        if abs(x1 - x2) <= SNAP_TOLERANCE_MM and abs(y1 - y2) <= SNAP_TOLERANCE_MM:
            continue
        key = _segment_key(segment)
        if key not in unique:
            (sx, sy), (ex, ey) = key
            unique[key] = (sx, sy, ex, ey)

    horizontal: dict[float, list[tuple[float, float]]] = {}
    vertical: dict[float, list[tuple[float, float]]] = {}
    diagonal: list[tuple[float, float, float, float]] = []
    for x1, y1, x2, y2 in unique.values():
        if abs(y1 - y2) <= SNAP_TOLERANCE_MM:
            horizontal.setdefault(round(y1, 4), []).append((min(x1, x2), max(x1, x2)))
        elif abs(x1 - x2) <= SNAP_TOLERANCE_MM:
            vertical.setdefault(round(x1, 4), []).append((min(y1, y2), max(y1, y2)))
        else:
            diagonal.append((x1, y1, x2, y2))

    merged: list[tuple[float, float, float, float]] = []
    for y, intervals in sorted(horizontal.items()):
        current_start: float | None = None
        current_end: float | None = None
        for start, end in sorted(intervals):
            if current_start is None or current_end is None:
                current_start, current_end = start, end
            elif start <= current_end + SNAP_TOLERANCE_MM:
                current_end = max(current_end, end)
            else:
                merged.append((current_start, y, current_end, y))
                current_start, current_end = start, end
        if current_start is not None and current_end is not None:
            merged.append((current_start, y, current_end, y))

    for x, intervals in sorted(vertical.items()):
        current_start = None
        current_end = None
        for start, end in sorted(intervals):
            if current_start is None or current_end is None:
                current_start, current_end = start, end
            elif start <= current_end + SNAP_TOLERANCE_MM:
                current_end = max(current_end, end)
            else:
                merged.append((x, current_start, x, current_end))
                current_start, current_end = start, end
        if current_start is not None and current_end is not None:
            merged.append((x, current_start, x, current_end))

    merged.extend(diagonal)
    return merged


def _existing_junction_points(content: str) -> set[tuple[float, float]]:
    points: set[tuple[float, float]] = set()
    for match in re.finditer(r"\(junction\s+\(at\s+([-\d.]+)\s+([-\d.]+)\)", content):
        points.add(_coord_pair_key(float(match.group(1)), float(match.group(2))))
    return points


def _junction_block(x_mm: float, y_mm: float) -> str:
    return (
        f"\t(junction (at {_fmt_mm(x_mm)} {_fmt_mm(y_mm)})\n"
        "\t\t(diameter 0)\n"
        f'\t\t(uuid "{new_uuid()}")\n'
        "\t)"
    )


def _insert_junctions_for_batch(
    sexpr_content: str,
    points: list[tuple[float, float]],
) -> str:
    """Insert missing KiCad junction blocks for the supplied coordinates."""
    existing = _existing_junction_points(sexpr_content)
    updated = sexpr_content
    for x_mm, y_mm in sorted({_coord_pair_key(x, y) for x, y in points}):
        if (x_mm, y_mm) in existing:
            continue
        updated = _append_before_sheet_instances(updated, _junction_block(x_mm, y_mm))
        existing.add((x_mm, y_mm))
    return updated


def _segment_intersects_bbox(
    segment: tuple[float, float, float, float],
    bbox: BBox,
) -> bool:
    x1, y1, x2, y2 = segment
    if abs(y1 - y2) <= SNAP_TOLERANCE_MM:
        if bbox.y_min + SNAP_TOLERANCE_MM < y1 < bbox.y_max - SNAP_TOLERANCE_MM:
            return max(min(x1, x2), bbox.x_min) <= min(max(x1, x2), bbox.x_max)
        return False
    if abs(x1 - x2) <= SNAP_TOLERANCE_MM:
        if bbox.x_min + SNAP_TOLERANCE_MM < x1 < bbox.x_max - SNAP_TOLERANCE_MM:
            return max(min(y1, y2), bbox.y_min) <= min(max(y1, y2), bbox.y_max)
        return False
    return False


def _route_crosses_obstacle(
    segments: list[tuple[float, float, float, float]],
    obstacles: list[BBox],
) -> bool:
    return any(
        _segment_intersects_bbox(segment, obstacle)
        for segment in segments
        for obstacle in obstacles
    )


def _route_avoiding_obstacles(
    start: tuple[float, float],
    end: tuple[float, float],
    obstacles: list[BBox],
    snap_to_grid: bool,
) -> tuple[list[tuple[float, float, float, float]], str | None]:
    """Route L-shape first, then a simple padded Z-route around obstacles."""
    direct = _deduplicate_segments(_manhattan_segments(start, end, snap_to_grid))
    padded = [obstacle.padded(5.0) for obstacle in obstacles]
    if not direct or not _route_crosses_obstacle(direct, padded):
        return direct, None

    router = SchematicRouter(
        grid_mm=SCHEMATIC_GRID_MM,
        obstacles=[
            RouterBBox(obstacle.x_min, obstacle.y_min, obstacle.x_max, obstacle.y_max)
            for obstacle in padded
        ],
    )
    routed = router.route(start, end, max_bends=4)
    if routed:
        return _deduplicate_segments(routed), None

    max_y = max(max(start[1], end[1]), *(bbox.y_max for bbox in padded))
    min_y = min(min(start[1], end[1]), *(bbox.y_min for bbox in padded))
    candidate_offsets = [max_y + SCHEMATIC_GRID_MM, min_y - SCHEMATIC_GRID_MM]
    for via_y in candidate_offsets:
        raw = [
            (start[0], start[1], start[0], via_y),
            (start[0], via_y, end[0], via_y),
            (end[0], via_y, end[0], end[1]),
        ]
        segments = _deduplicate_segments(raw)
        if segments and not _route_crosses_obstacle(segments, padded):
            return segments, None
    return direct, "WARNING: obstacle_bypass_failed"


def _resolve_net_endpoint(
    endpoint: dict[str, Any],
    net_name: str,
    symbol_points: dict[str, dict[str, tuple[float, float]]],
    symbol_pin_aliases: dict[str, dict[str, tuple[float, float]]],
    symbol_centers: dict[str, tuple[float, float]],
    power_points: dict[str, tuple[float, float]],
    label_points: dict[str, tuple[float, float]],
) -> tuple[tuple[float, float] | None, str | None, str]:
    reference = _endpoint_reference(endpoint)
    if reference is not None:
        pin = _endpoint_pin(endpoint)
        if reference not in symbol_centers:
            return None, f"reference '{reference}' was not found", "missing_reference"
        if pin is not None:
            if pin in symbol_points.get(reference, {}):
                return symbol_points[reference][pin], None, "pin_number"
            alias_positions = symbol_pin_aliases.get(reference, {})
            if pin in alias_positions:
                return alias_positions[pin], None, "pin_alias"
            normalized_pin = _normalize_pin_alias(pin)
            if normalized_pin and normalized_pin in alias_positions:
                return alias_positions[normalized_pin], None, "pin_alias"
            return (
                None,
                f"pin '{pin}' was not found on symbol '{reference}'",
                "missing_pin",
            )
        point = symbol_centers.get(reference)
        if point is None:
            return None, f"reference '{reference}' has no resolved placement", "missing_reference"
        return point, None, "symbol_center"

    power = _endpoint_power(endpoint)
    if power is not None:
        point = power_points.get(power.upper())
        if point is None:
            return None, f"power symbol '{power}' is not placed", "missing_power"
        return point, None, "power"

    label = _endpoint_label(endpoint)
    if label is not None:
        point = label_points.get(label)
        if point is None:
            return None, f"label '{label}' is not placed", "missing_label"
        return point, None, "label"

    if _is_power_net(net_name):
        point = power_points.get(net_name.upper())
        if point is None:
            return (
                None,
                f"net '{net_name}' expected a power symbol but none is placed",
                "missing_power",
            )
        return point, None, "power"
    point = label_points.get(net_name)
    if point is None:
        return None, f"net '{net_name}' expected a label but none is placed", "missing_label"
    return point, None, "label"


def _endpoint_specs_for_routing(
    net: dict[str, Any],
    power_points: dict[str, tuple[float, float]],
    label_points: dict[str, tuple[float, float]],
) -> list[dict[str, Any]]:
    name = _net_name(net)
    endpoints = _net_endpoints(net)
    if _is_power_net(name) and name.upper() in power_points and not any(
        _endpoint_power(endpoint) for endpoint in endpoints
    ):
        endpoints.append({"power": name})
    elif name in label_points and not any(_endpoint_label(endpoint) for endpoint in endpoints):
        endpoints.append({"label": name})
    return endpoints


def _describe_net_endpoint(endpoint: dict[str, Any]) -> str:
    reference = _endpoint_reference(endpoint)
    if reference is not None:
        pin = _endpoint_pin(endpoint)
        return f"{reference}.{pin}" if pin else reference

    power = _endpoint_power(endpoint)
    if power is not None:
        return f"power:{power}"

    label = _endpoint_label(endpoint)
    if label is not None:
        return f"label:{label}"

    return "<unresolved-endpoint>"


def _plan_netlist_wires(
    symbols: list[AddSymbolInput],
    powers: list[PowerSymbolInput],
    labels: list[AddLabelInput],
    nets: list[dict[str, Any]],
    snap_to_grid: bool,
) -> tuple[list[dict[str, float | bool]], list[dict[str, Any]], dict[str, int]]:
    symbol_points: dict[str, dict[str, tuple[float, float]]] = {}
    symbol_pin_aliases: dict[str, dict[str, tuple[float, float]]] = {}
    symbol_centers: dict[str, tuple[float, float]] = {}
    for symbol in symbols:
        x, y = _snap_point(symbol.x_mm, symbol.y_mm, snap_to_grid and symbol.snap_to_grid)
        symbol_centers[symbol.reference] = (x, y)
        symbol_points[symbol.reference] = get_pin_positions(
            symbol.library,
            symbol.symbol_name,
            x,
            y,
            symbol.rotation,
            symbol.unit,
        )
        symbol_pin_aliases[symbol.reference] = get_pin_alias_positions(
            symbol.library,
            symbol.symbol_name,
            x,
            y,
            symbol.rotation,
            symbol.unit,
        )

    power_points: dict[str, tuple[float, float]] = {}
    for power in powers:
        x, y = _snap_point(power.x_mm, power.y_mm, snap_to_grid and power.snap_to_grid)
        power_points.setdefault(power.name.upper(), (x, y))

    label_points: dict[str, tuple[float, float]] = {}
    for label in labels:
        x, y = _snap_point(label.x_mm, label.y_mm, snap_to_grid and label.snap_to_grid)
        label_points.setdefault(label.name, (x, y))

    routed_segments: list[dict[str, float | bool]] = []
    unresolved_nets: list[dict[str, Any]] = []
    seen_segments: set[tuple[tuple[float, float], tuple[float, float]]] = set()
    resolution_stats = {
        "resolved_endpoints": 0,
        "unresolved_endpoints": 0,
        "pin_alias_resolutions": 0,
        "symbol_center_resolutions": 0,
    }
    for net in nets:
        net_name = _net_name(net)
        endpoints = _endpoint_specs_for_routing(net, power_points, label_points)
        resolved_points: list[tuple[float, float]] = []
        unresolved_endpoints: list[str] = []
        unresolved_details: list[str] = []
        for endpoint in endpoints:
            point, reason, resolution_kind = _resolve_net_endpoint(
                endpoint,
                net_name,
                symbol_points,
                symbol_pin_aliases,
                symbol_centers,
                power_points,
                label_points,
            )
            if point is None:
                endpoint_text = _describe_net_endpoint(endpoint)
                unresolved_endpoints.append(endpoint_text)
                unresolved_details.append(f"{endpoint_text}: {reason or 'unresolved endpoint'}")
                resolution_stats["unresolved_endpoints"] += 1
                continue
            resolved_points.append(point)
            resolution_stats["resolved_endpoints"] += 1
            if resolution_kind == "pin_alias":
                resolution_stats["pin_alias_resolutions"] += 1
            elif resolution_kind == "symbol_center":
                resolution_stats["symbol_center_resolutions"] += 1
        if len(resolved_points) < 2:
            unresolved_nets.append(
                {
                    "name": net_name or "<unnamed>",
                    "endpoint_count": len(endpoints),
                    "resolved_count": len(resolved_points),
                    "unresolved_endpoints": unresolved_endpoints,
                    "unresolved_details": unresolved_details,
                }
            )
            continue

        anchor = resolved_points[0]
        for point in resolved_points[1:]:
            for segment in _manhattan_segments(anchor, point, snap_to_grid):
                key = _segment_key(segment)
                if key in seen_segments:
                    continue
                seen_segments.add(key)
                routed_segments.append(
                    {
                        "x1_mm": segment[0],
                        "y1_mm": segment[1],
                        "x2_mm": segment[2],
                        "y2_mm": segment[3],
                        "snap_to_grid": False,
                    }
                )
    return routed_segments, unresolved_nets, resolution_stats


def _prepare_build_circuit_inputs(
    *,
    symbols: list[dict[str, Any]] | None = None,
    wires: list[dict[str, Any]] | None = None,
    labels: list[dict[str, Any]] | None = None,
    power_symbols: list[dict[str, Any]] | None = None,
    nets: list[dict[str, Any]] | None = None,
    snap_to_grid: bool = True,
    auto_layout: bool = False,
) -> tuple[
    list[AddSymbolInput],
    list[PowerSymbolInput],
    list[AddLabelInput],
    list[AddWireInput],
    list[dict[str, Any]],
    list[dict[str, float | bool]],
    list[dict[str, Any]],
    dict[str, int],
]:
    raw_symbols = [dict(item) for item in (symbols or [])]
    raw_powers = [dict(item) for item in (power_symbols or [])]
    raw_labels = [dict(item) for item in (labels or [])]
    raw_wires = [dict(item) for item in (wires or [])]
    raw_nets = [dict(item) for item in (nets or [])]
    if auto_layout:
        if raw_nets:
            raw_symbols, raw_powers, raw_labels = _apply_netlist_auto_layout(
                raw_symbols,
                raw_powers,
                raw_labels,
                raw_nets,
            )
        else:
            raw_symbols, raw_powers, raw_labels = _apply_basic_auto_layout(
                raw_symbols,
                raw_powers,
                raw_labels,
            )

    validated_symbols = [AddSymbolInput.model_validate(item) for item in raw_symbols]
    validated_powers = [PowerSymbolInput.model_validate(item) for item in raw_powers]
    validated_wires = [AddWireInput.model_validate(item) for item in raw_wires]
    validated_labels = [AddLabelInput.model_validate(item) for item in raw_labels]
    for symbol in validated_symbols:
        available_units = get_symbol_available_units(symbol.library, symbol.symbol_name)
        if available_units and symbol.unit not in available_units:
            raise ValueError(
                f"Symbol '{symbol.library}:{symbol.symbol_name}' does not support unit "
                f"{symbol.unit}. Available units: {_format_available_units(available_units)}."
            )

    generated_wires: list[dict[str, float | bool]] = []
    unresolved_nets: list[dict[str, Any]] = []
    resolution_stats = {
        "resolved_endpoints": 0,
        "unresolved_endpoints": 0,
        "pin_alias_resolutions": 0,
        "symbol_center_resolutions": 0,
    }
    if raw_nets:
        generated_wires, unresolved_nets, resolution_stats = _plan_netlist_wires(
            validated_symbols,
            validated_powers,
            validated_labels,
            raw_nets,
            snap_to_grid,
        )
        validated_wires.extend(AddWireInput.model_validate(item) for item in generated_wires)

    return (
        validated_symbols,
        validated_powers,
        validated_labels,
        validated_wires,
        raw_nets,
        generated_wires,
        unresolved_nets,
        resolution_stats,
    )


def _render_net_compilation_report(
    *,
    symbols: list[AddSymbolInput],
    powers: list[PowerSymbolInput],
    labels: list[AddLabelInput],
    explicit_wires: int,
    nets: list[dict[str, Any]],
    generated_wires: list[dict[str, float | bool]],
    unresolved_nets: list[dict[str, Any]],
    resolution_stats: dict[str, int],
    auto_layout: bool,
) -> str:
    lines = ["Net compilation analysis:"]
    lines.extend(
        [
            f"- Symbols: {len(symbols)}",
            f"- Power symbols: {len(powers)}",
            f"- Labels: {len(labels)}",
            f"- Explicit wires supplied: {explicit_wires}",
            f"- Nets requested: {len(nets)}",
            f"- Routable nets: {len(nets) - len(unresolved_nets)}",
            f"- Unresolved nets: {len(unresolved_nets)}",
            f"- Generated wire segments: {len(generated_wires)}",
            f"- Resolved endpoints: {resolution_stats['resolved_endpoints']}",
            f"- Unresolved endpoints: {resolution_stats['unresolved_endpoints']}",
            f"- Pin alias matches: {resolution_stats['pin_alias_resolutions']}",
            f"- Symbol-center fallbacks: {resolution_stats['symbol_center_resolutions']}",
            f"- Auto-layout: {'enabled' if auto_layout else 'disabled'}",
        ]
    )
    if unresolved_nets:
        lines.append("Unresolved nets:")
        for item in unresolved_nets[:12]:
            missing = ", ".join(cast(list[str], item["unresolved_endpoints"])) or "all endpoints"
            lines.append(
                f"- {item['name']}: resolved {item['resolved_count']}/{item['endpoint_count']} "
                f"endpoint(s); missing {missing}"
            )
            for detail in cast(list[str], item.get("unresolved_details", []))[:3]:
                lines.append(f"  - {detail}")
    else:
        lines.append("- All requested nets resolved to routable endpoints.")
    return "\n".join(lines)


def _point_key(x: float, y: float) -> tuple[float, float]:
    return (round(float(x), 4), round(float(y), 4))


def _point_on_segment(point: tuple[float, float], wire: dict[str, float]) -> bool:
    px, py = point
    x1 = float(wire["x1"])
    y1 = float(wire["y1"])
    x2 = float(wire["x2"])
    y2 = float(wire["y2"])
    if abs(x1 - x2) <= SNAP_TOLERANCE_MM:
        return (
            abs(px - x1) <= SNAP_TOLERANCE_MM
            and min(y1, y2) - SNAP_TOLERANCE_MM <= py <= max(y1, y2) + SNAP_TOLERANCE_MM
        )
    if abs(y1 - y2) <= SNAP_TOLERANCE_MM:
        return (
            abs(py - y1) <= SNAP_TOLERANCE_MM
            and min(x1, x2) - SNAP_TOLERANCE_MM <= px <= max(x1, x2) + SNAP_TOLERANCE_MM
        )
    return False


def _split_lib_id(lib_id: str) -> tuple[str, str]:
    if ":" not in lib_id:
        raise ValueError(f"Library identifier '{lib_id}' is invalid.")
    library, symbol_name = lib_id.split(":", 1)
    return library, symbol_name


def _build_connectivity_groups(sch_file: Path) -> list[dict[str, Any]]:
    data = parse_schematic_file(sch_file)
    parent: dict[tuple[float, float], tuple[float, float]] = {}

    def find(point: tuple[float, float]) -> tuple[float, float]:
        root = parent.setdefault(point, point)
        if root != point:
            root = find(root)
            parent[point] = root
        return root

    def union(left: tuple[float, float], right: tuple[float, float]) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    for wire in data["wires"]:
        start = _point_key(wire["x1"], wire["y1"])
        end = _point_key(wire["x2"], wire["y2"])
        union(start, end)

    def attach(point: tuple[float, float]) -> tuple[float, float]:
        key = _point_key(*point)
        if key in parent:
            return find(key)
        for wire in data["wires"]:
            if _point_on_segment(key, wire):
                anchor = _point_key(wire["x1"], wire["y1"])
                return find(anchor)
        return find(key)

    groups: dict[tuple[float, float], dict[str, Any]] = {}

    def ensure_group(point: tuple[float, float]) -> dict[str, Any]:
        root = attach(point)
        return groups.setdefault(
            root,
            {
                "points": set(),
                "labels": set(),
                "power": set(),
                "pins": [],
            },
        )

    for wire in data["wires"]:
        group = ensure_group(_point_key(wire["x1"], wire["y1"]))
        group["points"].add(_point_key(wire["x1"], wire["y1"]))
        group["points"].add(_point_key(wire["x2"], wire["y2"]))

    for label in data["labels"]:
        group = ensure_group((float(label["x"]), float(label["y"])))
        group["points"].add(_point_key(label["x"], label["y"]))
        group["labels"].add(str(label["name"]))

    for power_symbol in data["power_symbols"]:
        group = ensure_group((float(power_symbol["x"]), float(power_symbol["y"])))
        group["points"].add(_point_key(power_symbol["x"], power_symbol["y"]))
        group["power"].add(str(power_symbol["value"]))

    for symbol in data["symbols"]:
        library, symbol_name = _split_lib_id(str(symbol["lib_id"]))
        pin_positions = get_pin_positions(
            library,
            symbol_name,
            float(symbol["x"]),
            float(symbol["y"]),
            int(symbol["rotation"]),
            int(symbol["unit"]),
        )
        for pin_number, point in pin_positions.items():
            group = ensure_group(point)
            group["points"].add(_point_key(*point))
            group["pins"].append(
                {
                    "reference": symbol["reference"],
                    "pin": pin_number,
                    "value": symbol["value"],
                }
            )

    normalized_groups: list[dict[str, Any]] = []
    for group in groups.values():
        names = sorted({*group["labels"], *group["power"]})
        normalized_groups.append(
            {
                "names": names,
                "points": sorted(group["points"]),
                "pins": sorted(
                    group["pins"],
                    key=lambda item: (item["reference"], item["pin"]),
                ),
            }
        )
    return sorted(
        normalized_groups,
        key=lambda group: (
            group["names"][0] if group["names"] else "~unnamed",
            len(group["pins"]),
            len(group["points"]),
        ),
    )


def _project_name() -> str:
    cfg = get_config()
    if cfg.project_file is not None:
        return cfg.project_file.stem
    return "KiCadMCP"


def _iter_child_sheet_paths(sch_file: Path) -> list[tuple[str, Path]]:
    try:
        schematic = _load_kicad_schematic(sch_file)
    except Exception as exc:
        logger.debug(
            "schematic_sheet_discovery_failed",
            schematic_file=str(sch_file),
            error=str(exc),
        )
        return []

    discovered: list[tuple[str, Path]] = []

    def visit(
        current_name: str,
        current_path: Path,
        current_schematic: _LoadedSchematicLike,
    ) -> None:
        hierarchy = current_schematic.sheets.get_sheet_hierarchy()
        children = hierarchy.get("root", {}).get("children", [])
        for child in children:
            child_name = str(child.get("name", "Sheet"))
            child_file = current_path.parent / str(child.get("filename", ""))
            display_name = f"{current_name}/{child_name}" if current_name else child_name
            discovered.append((display_name, child_file))
            if child_file.exists():
                try:
                    visit(display_name, child_file, _load_kicad_schematic(child_file))
                except Exception as exc:
                    logger.debug(
                        "schematic_child_sheet_load_failed",
                        sheet=display_name,
                        schematic_file=str(child_file),
                        error=str(exc),
                    )

    visit("", sch_file, schematic)
    return discovered


def wire_block(x1: float, y1: float, x2: float, y2: float, kind: str = "wire") -> str:
    """Create a schematic wire or bus block."""
    return (
        f"\t({kind}\n"
        f"\t\t(pts (xy {_fmt_mm(x1)} {_fmt_mm(y1)}) (xy {_fmt_mm(x2)} {_fmt_mm(y2)}))\n"
        "\t\t(stroke (width 0) (type solid))\n"
        f'\t\t(uuid "{new_uuid()}")\n'
        "\t)"
    )


def label_block(
    name: str,
    x: float,
    y: float,
    rotation: int = 0,
    global_label: bool = False,
    shape: str | None = None,
    kind: str | None = None,
) -> str:
    """Create a schematic label block."""
    effective_kind = kind or ("global_label" if global_label else "label")
    effective_shape = shape
    if effective_kind == "global_label" and effective_shape is None:
        effective_shape = "bidirectional"
    shape_line = f"\t\t(shape {effective_shape})\n" if effective_shape else ""
    return (
        f"\t({effective_kind} {_sexpr_string(name)}\n"
        f"{shape_line}"
        f"\t\t(at {_fmt_mm(x)} {_fmt_mm(y)} {rotation})\n"
        "\t\t(effects (font (size 1.524 1.524)))\n"
        f'\t\t(uuid "{new_uuid()}")\n'
        "\t)"
    )


def no_connect_block(x: float, y: float) -> str:
    """Create a no-connect marker."""
    return f'\t(no_connect (at {_fmt_mm(x)} {_fmt_mm(y)}) (uuid "{new_uuid()}"))'


def bus_entry_block(x: float, y: float, direction: str) -> str:
    """Create a bus wire entry block."""
    offset_map = {
        "up_right": (2.54, -2.54),
        "down_right": (2.54, 2.54),
        "up_left": (-2.54, -2.54),
        "down_left": (-2.54, 2.54),
    }
    dx, dy = offset_map[direction]
    return (
        "\t(bus_entry\n"
        f"\t\t(at {_fmt_mm(x)} {_fmt_mm(y)})\n"
        f"\t\t(size {_fmt_mm(dx)} {_fmt_mm(dy)})\n"
        "\t\t(stroke (width 0) (type solid))\n"
        f'\t\t(uuid "{new_uuid()}")\n'
        "\t)"
    )


def place_symbol_block(
    lib_id: str,
    x: float,
    y: float,
    reference: str,
    value: str,
    footprint: str = "",
    rotation: int = 0,
    unit: int = 1,
    project_name: str = "KiCadMCP",
    root_uuid: str = "",
) -> str:
    """Build a schematic symbol instance block."""
    symbol_uuid = new_uuid()
    root = root_uuid or new_uuid()
    is_power_symbol = lib_id.startswith("power:") or reference.startswith("#PWR")
    if is_power_symbol and value.upper().startswith("GND"):
        value_y = y + 5.08
        reference_y = y + 6.35
    elif is_power_symbol:
        value_y = y - 5.08
        reference_y = y - 6.35
    else:
        reference_y = y - 3.81
        value_y = y + 3.81
    reference_effects = (
        "\t\t\t(effects (font (size 1.27 1.27)) (hide yes))"
        if is_power_symbol
        else "\t\t\t(effects (font (size 1.27 1.27)))"
    )
    return (
        "\t(symbol\n"
        f"\t\t(lib_id {_sexpr_string(lib_id)})\n"
        f"\t\t(at {_fmt_mm(x)} {_fmt_mm(y)} {rotation})\n"
        f"\t\t(unit {unit})\n"
        "\t\t(exclude_from_sim no)\n"
        "\t\t(in_bom yes)\n"
        "\t\t(on_board yes)\n"
        "\t\t(dnp no)\n"
        f'\t\t(uuid "{symbol_uuid}")\n'
        f'\t\t(property "Reference" {_sexpr_string(reference)}\n'
        f"\t\t\t(at {_fmt_mm(x)} {_fmt_mm(reference_y)} {rotation})\n"
        f"{reference_effects}\n"
        "\t\t)\n"
        f'\t\t(property "Value" {_sexpr_string(value)}\n'
        f"\t\t\t(at {_fmt_mm(x)} {_fmt_mm(value_y)} {rotation})\n"
        "\t\t\t(effects (font (size 1.27 1.27)))\n"
        "\t\t)\n"
        f'\t\t(property "Footprint" {_sexpr_string(footprint)}\n'
        f"\t\t\t(at {_fmt_mm(x)} {_fmt_mm(y)} {rotation})\n"
        "\t\t\t(effects (font (size 1.27 1.27)) (hide yes))\n"
        "\t\t)\n"
        '\t\t(property "Datasheet" "~"\n'
        f"\t\t\t(at {_fmt_mm(x)} {_fmt_mm(y)} 0)\n"
        "\t\t\t(effects (font (size 1.27 1.27)) (hide yes))\n"
        "\t\t)\n"
        "\t\t(instances\n"
        f"\t\t\t(project {_sexpr_string(project_name)}\n"
        f'\t\t\t\t(path "/{root}"\n'
        f"\t\t\t\t\t(reference {_sexpr_string(reference)}) (unit {unit})\n"
        "\t\t\t\t)\n"
        "\t\t\t)\n"
        "\t\t)\n"
        "\t)"
    )


def _append_before_sheet_instances(content: str, block: str) -> str:
    marker = "\t(sheet_instances"
    if marker in content:
        return content.replace(marker, f"{block}\n{marker}", 1)
    return content.rstrip().rstrip(")") + f"\n{block}\n)\n"


def _validate_schematic_text(content: str) -> None:
    depth = 0
    in_string = False
    escaped = False
    for char in content:
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
        elif char == '"':
            in_string = True
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth < 0:
                break
    if depth != 0 or in_string:
        raise ValueError("Refusing to write an invalid schematic with unbalanced parentheses.")


def _find_placed_symbol_blocks(
    content: str,
    reference: str,
) -> list[tuple[str, int, int, dict[str, Any]]]:
    """Locate placed symbol instance blocks by reference designator."""
    matches: list[tuple[str, int, int, dict[str, Any]]] = []
    cursor = 0
    while cursor < len(content):
        if content[cursor:].startswith("(symbol"):
            block, length = _extract_block(content, cursor)
            if block:
                parsed = _parse_symbol_block(block)
                if parsed is not None and parsed["reference"] == reference:
                    matches.append((block, cursor, cursor + length, parsed))
                cursor += length
                continue
        cursor += 1
    return matches


def _find_placed_symbol_block(
    content: str,
    reference: str,
) -> tuple[str, int, int, dict[str, Any]] | None:
    """Locate the first placed symbol instance block by reference designator."""
    matches = _find_placed_symbol_blocks(content, reference)
    return matches[0] if matches else None


def _schematic_state_path(filename: str) -> Path:
    cfg = get_config()
    if cfg.project_dir is None:
        raise ValueError("No active project is configured.")
    target = cfg.project_dir / _SCHEMATIC_STATE_DIRNAME
    target.mkdir(parents=True, exist_ok=True)
    return target / filename


def _load_schematic_state(filename: str, default: dict[str, Any]) -> dict[str, Any]:
    path = _schematic_state_path(filename)
    if not path.exists():
        path.write_text(json.dumps(default, indent=2), encoding="utf-8")
        return dict(default)
    return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))


def _save_schematic_state(filename: str, payload: dict[str, Any]) -> Path:
    path = _schematic_state_path(filename)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def _symbol_by_reference(reference: str) -> dict[str, Any]:
    symbols = parse_schematic_file(_get_schematic_file())["symbols"]
    match = next(
        (symbol for symbol in symbols if str(symbol.get("reference", "")) == reference),
        None,
    )
    if match is None:
        raise ValueError(f"Reference '{reference}' was not found in the schematic.")
    return cast(dict[str, Any], match)


def _next_reference(prefix: str) -> str:
    symbols = parse_schematic_file(_get_schematic_file())["symbols"]
    highest = 0
    pattern = re.compile(rf"^{re.escape(prefix)}(\d+)$")
    for symbol in symbols:
        reference = str(symbol.get("reference", ""))
        match = pattern.match(reference)
        if match is not None:
            highest = max(highest, int(match.group(1)))
    return f"{prefix}{highest + 1}"


def _transactional_write_to_schematic(mutator: Callable[[str], str]) -> str:
    """Read, mutate, validate, and atomically rewrite the active schematic."""
    sch_file = _get_schematic_file()
    current = sch_file.read_text(encoding="utf-8")
    updated = _normalize_schematic_wire_connectivity(mutator(current))
    _validate_schematic_text(updated)
    with NamedTemporaryFile("w", encoding="utf-8", delete=False, dir=sch_file.parent) as handle:
        handle.write(updated)
        temp_path = Path(handle.name)
    temp_path.replace(sch_file)
    clear_ttl_cache()
    return str(sch_file)


def transactional_write(mutator: Callable[[str], str]) -> str:
    """Read, mutate, validate, and atomically rewrite the active schematic."""
    return get_schematic_backend().transactional_write(mutator)


def _update_symbol_property_text_fallback(reference: str, field: str, value: str) -> str:
    """Update a symbol property in the active schematic."""
    payload = UpdatePropertiesInput(reference=reference, field=field, value=value)

    def mutator(current: str) -> str:
        pattern = re.compile(
            rf'(\(property\s+"{re.escape(payload.field)}"\s+")([^"]*)(")',
            re.DOTALL,
        )
        match = _find_placed_symbol_block(current, payload.reference)
        if match is None:
            raise ValueError(f"Reference '{payload.reference}' was not found in the schematic.")
        block, start, end, parsed = match
        if pattern.search(block):
            escaped_value = _escape_sexpr_string(payload.value)
            new_block = pattern.sub(
                lambda match: f"{match.group(1)}{escaped_value}{match.group(3)}",
                block,
                count=1,
            )
        else:
            insert_point = block.rfind("\t\t(instances")
            if insert_point == -1:
                insert_point = block.rfind("\n\t)")
            if insert_point == -1:
                raise ValueError(f"Could not update '{payload.reference}' in the schematic.")
            x = parsed["x"]
            y = parsed["y"]
            rotation = parsed["rotation"]
            property_block = (
                f"\t\t(property {_sexpr_string(payload.field)} {_sexpr_string(payload.value)}\n"
                f"\t\t\t(at {_fmt_mm(x)} {_fmt_mm(y)} {rotation})\n"
                "\t\t\t(effects (font (size 1.27 1.27)) (hide yes))\n"
                "\t\t)\n"
            )
            new_block = block[:insert_point] + property_block + block[insert_point:]
        return current[:start] + new_block + current[end:]

    _transactional_write_to_schematic(mutator)
    return f"Updated {payload.reference}.{payload.field}."


def update_symbol_property(reference: str, field: str, value: str) -> str:
    """Update a symbol property through the active backend adapter."""
    return get_schematic_backend().update_symbol_property(reference, field, value)


def _parse_wire_block(block: str) -> dict[str, Any] | None:
    pts_match = re.search(
        (
            r"\(pts\s+\(xy\s+([-\d.]+)\s+([-\d.]+)\)\s+"
            r"\(xy\s+([-\d.]+)\s+([-\d.]+)\)\s*\)"
        ),
        block,
    )
    if pts_match is None:
        return None
    parsed: dict[str, Any] = {
        "x1": float(pts_match.group(1)),
        "y1": float(pts_match.group(2)),
        "x2": float(pts_match.group(3)),
        "y2": float(pts_match.group(4)),
    }
    uuid_match = re.search(r'\(uuid\s+"([^"]+)"\)', block)
    if uuid_match is not None:
        parsed["uuid"] = uuid_match.group(1)
    return parsed


def _wire_id_matches(actual_id: str, requested_id: str) -> bool:
    normalized_actual = actual_id.casefold()
    normalized_requested = requested_id.casefold()
    return (
        normalized_actual == normalized_requested
        or normalized_actual.startswith(normalized_requested)
        or normalized_requested.startswith(normalized_actual)
    )


def _shift_symbol_block(block: str, dx_mm: float, dy_mm: float) -> str:
    at_pattern = re.compile(
        rf"(\(at\s+)({_FLOAT_PATTERN})\s+({_FLOAT_PATTERN})(\s+{_FLOAT_PATTERN}\))"
    )

    def repl(match: re.Match[str]) -> str:
        shifted_x = float(match.group(2)) + dx_mm
        shifted_y = float(match.group(3)) + dy_mm
        return (
            f"{match.group(1)}{_fmt_mm(shifted_x)} "
            f"{_fmt_mm(shifted_y)}{match.group(4)}"
        )

    return at_pattern.sub(repl, block)


def _symbol_connection_points(parsed: dict[str, Any]) -> set[tuple[float, float]]:
    points = {_coord_pair_key(parsed["x"], parsed["y"])}
    lib_id = str(parsed.get("lib_id", ""))
    if lib_id.startswith("power:"):
        return points
    try:
        library, symbol_name = _split_lib_id(lib_id)
        pin_positions = get_pin_positions(
            library,
            symbol_name,
            float(parsed["x"]),
            float(parsed["y"]),
            int(parsed["rotation"]),
            int(parsed["unit"]),
        )
    except Exception as exc:
        logger.debug(
            "schematic_symbol_connection_points_failed",
            reference=str(parsed.get("reference", "")),
            error=str(exc),
        )
        return points

    points.update(_coord_pair_key(x, y) for x, y in pin_positions.values())
    return points


def _reload_schematic_via_ipc() -> str:
    try:
        from kipy.proto.common.commands import editor_commands_pb2
        from kipy.proto.common.types.base_types_pb2 import DocumentType
    except Exception as exc:
        logger.debug("schematic_reload_import_unavailable", error=str(exc))
        return "The schematic was updated. Reload it manually in KiCad if needed."

    try:
        kicad = get_kicad()
    except KiCadConnectionError:
        return "The schematic was updated. KiCad is not connected, so reload it manually."

    try:
        documents = kicad.get_open_documents(DocumentType.DOCTYPE_SCHEMATIC)
        if not documents:
            return "The schematic was updated. No open KiCad schematic was found to reload."
        command = editor_commands_pb2.RevertDocument()
        command.document.CopyFrom(documents[0])
        kicad._client.send(command, type(None).__mro__[0])
        return "The schematic was updated and KiCad was asked to reload it."
    except Exception as exc:
        logger.debug("schematic_reload_failed", error=str(exc))
        return "The schematic was updated. Reload it manually in KiCad if needed."


def _reload_schematic() -> str:
    """Reload the schematic through the active backend adapter."""
    return get_schematic_backend().reload_schematic()


def register(mcp: FastMCP) -> None:
    """Register schematic tools."""

    @mcp.tool()
    @ttl_cache(ttl_seconds=5)
    def sch_get_symbols() -> str:
        """List all schematic symbols."""
        data = parse_schematic_file(_get_schematic_file())
        symbols = data["symbols"] + data["power_symbols"]
        if not symbols:
            return "The active schematic contains no symbols."

        lines = [f"Symbols ({len(symbols)} total):"]
        for symbol in data["symbols"]:
            suffix = f" footprint={symbol['footprint']}" if symbol["footprint"] else ""
            lines.append(
                f"- {symbol['reference']} {symbol['value']} {symbol['lib_id']} @ "
                f"({symbol['x']:.2f}, {symbol['y']:.2f}) rot={symbol['rotation']} "
                f"unit={symbol['unit']}{suffix}"
            )
        if data["power_symbols"]:
            lines.append("Power symbols:")
            for symbol in data["power_symbols"]:
                lines.append(
                    f"- {symbol['reference']} {symbol['value']} @ "
                    f"({symbol['x']:.2f}, {symbol['y']:.2f}) unit={symbol['unit']}"
                )
        return "\n".join(lines)

    @mcp.tool()
    def sch_get_wires() -> str:
        """List all wires in the schematic."""
        wires = parse_schematic_file(_get_schematic_file())["wires"]
        if not wires:
            return "The active schematic contains no wires."
        lines = [f"Wires ({len(wires)} total):"]
        for wire in wires:
            identifier = f"{wire['uuid']} " if wire.get("uuid") else ""
            lines.append(
                f"- {identifier}({wire['x1']}, {wire['y1']}) -> ({wire['x2']}, {wire['y2']})"
            )
        return "\n".join(lines)

    @mcp.tool()
    def sch_get_labels() -> str:
        """List all labels in the schematic."""
        labels = parse_schematic_file(_get_schematic_file())["labels"]
        if not labels:
            return "The active schematic contains no labels."
        lines = [f"Labels ({len(labels)} total):"]
        lines.extend(
            f"- {label['name']} @ ({label['x']}, {label['y']}) rot={label['rotation']}"
            for label in labels
        )
        return "\n".join(lines)

    @mcp.tool()
    def sch_get_net_names() -> str:
        """List unique net names derived from labels."""
        labels = parse_schematic_file(_get_schematic_file())["labels"]
        names = sorted({label["name"] for label in labels})
        if not names:
            return "No named nets were found in the schematic."
        return "Named nets:\n" + "\n".join(f"- {name}" for name in names)

    @mcp.tool()
    def sch_add_symbol(
        library: str,
        symbol_name: str,
        x_mm: float,
        y_mm: float,
        reference: str,
        value: str,
        footprint: str = "",
        rotation: int = 0,
        snap_to_grid: bool = True,
        unit: int = 1,
    ) -> str:
        """Add a schematic symbol at an absolute coordinate.

        Coordinates snap to the 2.54 mm schematic grid by default; set
        snap_to_grid=False only when an exact off-grid coordinate is intentional.
        """
        payload = AddSymbolInput(
            library=library,
            symbol_name=symbol_name,
            x_mm=x_mm,
            y_mm=y_mm,
            reference=reference,
            value=value,
            footprint=footprint,
            rotation=rotation,
            snap_to_grid=snap_to_grid,
            unit=unit,
        )
        symbol_x, symbol_y = _snap_point(payload.x_mm, payload.y_mm, payload.snap_to_grid)
        snap_note = _snap_notice((payload.x_mm, payload.y_mm), (symbol_x, symbol_y))
        lib_def = load_lib_symbol(payload.library, payload.symbol_name)
        if lib_def is None:
            return f"Symbol '{payload.library}:{payload.symbol_name}' was not found."
        available_units = get_symbol_available_units(payload.library, payload.symbol_name)
        if available_units and payload.unit not in available_units:
            return (
                f"Symbol '{payload.library}:{payload.symbol_name}' does not support unit "
                f"{payload.unit}. Available units: {_format_available_units(available_units)}."
            )

        sch_file = _get_schematic_file()
        sch_data = parse_schematic_file(sch_file)
        root_uuid = sch_data["uuid"] or new_uuid()
        cfg = get_config()
        project_name = cfg.project_file.stem if cfg.project_file is not None else "KiCadMCP"
        lib_id = f"{payload.library}:{payload.symbol_name}"

        # Collision warning: does the insertion point overlap existing symbols?
        all_existing = sch_data["symbols"] + sch_data["power_symbols"]
        overlap_warning = _point_near_existing(symbol_x, symbol_y, all_existing)

        def mutator(current: str) -> str:
            updated = current
            if f'(symbol "{lib_id}"' not in updated:
                if "(lib_symbols)" in updated:
                    updated = updated.replace("(lib_symbols)", f"(lib_symbols\n\t{lib_def}\n\t)", 1)
                else:
                    updated = updated.replace(
                        "\t(lib_symbols\n", f"\t(lib_symbols\n\t{lib_def}\n", 1
                    )
            block = place_symbol_block(
                lib_id=lib_id,
                x=symbol_x,
                y=symbol_y,
                reference=payload.reference,
                value=payload.value,
                footprint=payload.footprint,
                rotation=payload.rotation,
                unit=payload.unit,
                project_name=project_name,
                root_uuid=root_uuid,
            )
            return _append_before_sheet_instances(updated, block)

        transactional_write(mutator)
        result = _reload_schematic()
        fp_warning = _validate_footprint(payload.footprint or "")
        parts = [p for p in [result, snap_note, overlap_warning, fp_warning] if p]
        return "\n".join(parts)

    @mcp.tool()
    def sch_add_wire(
        x1_mm: float,
        y1_mm: float,
        x2_mm: float,
        y2_mm: float,
        snap_to_grid: bool = True,
    ) -> str:
        """Add a schematic wire, snapping endpoints to the 2.54 mm grid by default."""
        payload = AddWireInput(
            x1_mm=x1_mm,
            y1_mm=y1_mm,
            x2_mm=x2_mm,
            y2_mm=y2_mm,
            snap_to_grid=snap_to_grid,
        )
        wire_coords = _snap_line(
            payload.x1_mm,
            payload.y1_mm,
            payload.x2_mm,
            payload.y2_mm,
            payload.snap_to_grid,
        )
        snap_note = _snap_notice(
            (payload.x1_mm, payload.y1_mm, payload.x2_mm, payload.y2_mm),
            wire_coords,
        )
        transactional_write(
            lambda current: _append_before_sheet_instances(
                current,
                wire_block(*wire_coords),
            )
        )
        result = _reload_schematic()
        return f"{result}\n{snap_note}" if snap_note else result

    @mcp.tool()
    def sch_add_label(
        name: str,
        x_mm: float,
        y_mm: float,
        rotation: int = 0,
        snap_to_grid: bool = True,
    ) -> str:
        """Add a schematic label, snapping its anchor to the 2.54 mm grid by default."""
        payload = AddLabelInput(
            name=name,
            x_mm=x_mm,
            y_mm=y_mm,
            rotation=rotation,
            snap_to_grid=snap_to_grid,
        )
        label_x, label_y = _snap_point(payload.x_mm, payload.y_mm, payload.snap_to_grid)
        snap_note = _snap_notice((payload.x_mm, payload.y_mm), (label_x, label_y))
        transactional_write(
            lambda current: _append_before_sheet_instances(
                current,
                label_block(payload.name, label_x, label_y, payload.rotation),
            )
        )
        result = _reload_schematic()
        return f"{result}\n{snap_note}" if snap_note else result

    @mcp.tool()
    def sch_add_power_symbol(
        name: str,
        x_mm: float,
        y_mm: float,
        rotation: int = 0,
        snap_to_grid: bool = True,
    ) -> str:
        """Add a power symbol, snapping its anchor to the 2.54 mm grid by default."""
        return str(
            sch_add_symbol(
                "power",
                name,
                x_mm,
                y_mm,
                f"#PWR{new_uuid()[:4]}",
                name,
                "",
                rotation,
                snap_to_grid,
            )
        )

    @mcp.tool()
    def sch_add_bus(
        x1_mm: float,
        y1_mm: float,
        x2_mm: float,
        y2_mm: float,
        snap_to_grid: bool = True,
    ) -> str:
        """Add a schematic bus, snapping endpoints to the 2.54 mm grid by default."""
        payload = AddBusInput(
            x1_mm=x1_mm,
            y1_mm=y1_mm,
            x2_mm=x2_mm,
            y2_mm=y2_mm,
            snap_to_grid=snap_to_grid,
        )
        bus_coords = _snap_line(
            payload.x1_mm,
            payload.y1_mm,
            payload.x2_mm,
            payload.y2_mm,
            payload.snap_to_grid,
        )
        snap_note = _snap_notice(
            (payload.x1_mm, payload.y1_mm, payload.x2_mm, payload.y2_mm),
            bus_coords,
        )
        transactional_write(
            lambda current: _append_before_sheet_instances(
                current,
                wire_block(*bus_coords, "bus"),
            )
        )
        result = _reload_schematic()
        return f"{result}\n{snap_note}" if snap_note else result

    @mcp.tool()
    def sch_add_bus_wire_entry(
        x_mm: float,
        y_mm: float,
        direction: str = "up_right",
        snap_to_grid: bool = True,
    ) -> str:
        """Add a bus wire entry marker, snapping its anchor to the 2.54 mm grid by default."""
        payload = AddBusWireEntryInput(
            x_mm=x_mm,
            y_mm=y_mm,
            direction=direction,
            snap_to_grid=snap_to_grid,
        )
        entry_x, entry_y = _snap_point(payload.x_mm, payload.y_mm, payload.snap_to_grid)
        snap_note = _snap_notice((payload.x_mm, payload.y_mm), (entry_x, entry_y))
        transactional_write(
            lambda current: _append_before_sheet_instances(
                current,
                bus_entry_block(entry_x, entry_y, payload.direction),
            )
        )
        result = _reload_schematic()
        return f"{result}\n{snap_note}" if snap_note else result

    @mcp.tool()
    def sch_add_no_connect(x_mm: float, y_mm: float, snap_to_grid: bool = True) -> str:
        """Add a no-connect marker, snapping it to the 2.54 mm grid by default."""
        payload = AddNoConnectInput(x_mm=x_mm, y_mm=y_mm, snap_to_grid=snap_to_grid)
        marker_x, marker_y = _snap_point(payload.x_mm, payload.y_mm, payload.snap_to_grid)
        snap_note = _snap_notice((payload.x_mm, payload.y_mm), (marker_x, marker_y))
        transactional_write(
            lambda current: _append_before_sheet_instances(
                current,
                no_connect_block(marker_x, marker_y),
            )
        )
        result = _reload_schematic()
        return f"{result}\n{snap_note}" if snap_note else result

    @mcp.tool()
    @headless_compatible
    def sch_set_hop_over(enabled: bool = True) -> str:
        """Toggle KiCad 10 hop-over display in the active project settings."""
        cfg = get_config()
        if cfg.project_file is None or not cfg.project_file.exists():
            raise ValueError(
                "No project file is configured. Call kicad_set_project() before changing "
                "schematic display settings."
            )
        try:
            project_payload = json.loads(cfg.project_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"Project file '{cfg.project_file}' does not contain valid JSON."
            ) from exc
        if not isinstance(project_payload, dict):
            raise ValueError("The active project file must contain a JSON object.")

        schematic_settings = cast(
            dict[str, object],
            project_payload.setdefault("schematic", {}),
        )
        schematic_settings["hop_over_display"] = bool(enabled)
        cfg.project_file.write_text(json.dumps(project_payload, indent=2), encoding="utf-8")
        return (
            f"Hop-over display set to {'enabled' if enabled else 'disabled'} in "
            f"{cfg.project_file}."
        )

    @mcp.tool()
    @headless_compatible
    def sch_list_swappable_pins(component_ref: str) -> str:
        """List candidate pins and units that can participate in a swap workflow."""
        symbol = _symbol_by_reference(component_ref)
        library, symbol_name = _split_lib_id(str(symbol.get("lib_id", "")))
        pins = sorted(
            {
                alias
                for alias in get_pin_alias_positions(
                    library,
                    symbol_name,
                    float(symbol.get("x", 0.0)),
                    float(symbol.get("y", 0.0)),
                    int(symbol.get("rotation", 0)),
                    int(symbol.get("unit", 1)),
                )
                if alias and alias.isdigit()
            },
            key=lambda item: int(item),
        )

        units = []
        sym_file = _get_symbol_library_dir() / f"{library}.kicad_sym"
        if sym_file.exists():
            content = sym_file.read_text(encoding="utf-8", errors="ignore")
            symbol_blocks = _collect_symbol_blocks(content, symbol_name)
            units = sorted(_available_units_from_blocks(symbol_blocks))

        return json.dumps(
            {
                "reference": component_ref,
                "pins": pins,
                "gates": units,
                "note": "Recorded swaps are stored as back-annotation intents in .kicad-mcp.",
            },
            indent=2,
        )

    @mcp.tool()
    @headless_compatible
    def sch_swap_pins(component_ref: str, pin_a: str, pin_b: str) -> str:
        """Record a pin-swap back-annotation intent for a component."""
        swappable = json.loads(sch_list_swappable_pins(component_ref))
        pins = cast(list[str], swappable.get("pins", []))
        if pin_a not in pins or pin_b not in pins:
            return (
                f"Pins '{pin_a}' and/or '{pin_b}' are not swappable candidates "
                f"for '{component_ref}'."
            )

        state = _load_schematic_state("pin_swaps.json", {"swaps": []})
        swaps = cast(list[dict[str, str]], state.setdefault("swaps", []))
        swaps.append(
            {
                "reference": component_ref,
                "pin_a": pin_a,
                "pin_b": pin_b,
            }
        )
        path = _save_schematic_state("pin_swaps.json", state)
        return f"Recorded pin swap {component_ref}:{pin_a}<->{pin_b} in {path}."

    @mcp.tool()
    @headless_compatible
    def sch_swap_gates(component_ref: str, gate_a: int, gate_b: int) -> str:
        """Record a gate-swap back-annotation intent for a multi-unit component."""
        swappable = json.loads(sch_list_swappable_pins(component_ref))
        gates = cast(list[int], swappable.get("gates", []))
        if gate_a not in gates or gate_b not in gates:
            return f"Gates '{gate_a}' and/or '{gate_b}' are not available on '{component_ref}'."

        state = _load_schematic_state("gate_swaps.json", {"swaps": []})
        swaps = cast(list[dict[str, object]], state.setdefault("swaps", []))
        swaps.append(
            {
                "reference": component_ref,
                "gate_a": gate_a,
                "gate_b": gate_b,
            }
        )
        path = _save_schematic_state("gate_swaps.json", state)
        return f"Recorded gate swap {component_ref}:{gate_a}<->{gate_b} in {path}."

    @mcp.tool()
    def sch_add_jumper(
        x_mm: float,
        y_mm: float,
        pins: int = 2,
        open_by_default: bool = True,
        snap_to_grid: bool = True,
    ) -> str:
        """Add a jumper symbol to the schematic."""
        if pins < 2 or pins > 3:
            raise ValueError("Only 2-pin and 3-pin jumpers are supported.")
        target_x, target_y = _snap_point(x_mm, y_mm, snap_to_grid)
        snap_note = _snap_notice((x_mm, y_mm), (target_x, target_y))
        reference = _next_reference("JP")
        value = f"Jumper_{pins}_{'Open' if open_by_default else 'Closed'}"
        lib_id = f"Jumper:{value}"
        transactional_write(
            lambda current: _append_before_sheet_instances(
                current,
                place_symbol_block(
                    lib_id=lib_id,
                    x=target_x,
                    y=target_y,
                    reference=reference,
                    value=value,
                ),
            )
        )
        result = _reload_schematic()
        detail = f"Added jumper '{reference}' ({value}) at ({target_x:.2f}, {target_y:.2f}) mm."
        return f"{detail}\n{result}\n{snap_note}" if snap_note else f"{detail}\n{result}"

    @mcp.tool()
    def sch_update_properties(reference: str, field: str, value: str) -> str:
        """Update a property on a placed symbol."""
        result = update_symbol_property(reference, field, value)
        return f"{result}\n{_reload_schematic()}"

    @mcp.tool()
    def sch_move_symbol(
        reference: str,
        x_mm: float,
        y_mm: float,
        snap_to_grid: bool = True,
    ) -> str:
        """Move an existing symbol instance to a new absolute coordinate."""
        payload = MoveSymbolInput(
            reference=reference,
            x_mm=x_mm,
            y_mm=y_mm,
            snap_to_grid=snap_to_grid,
        )
        target_x, target_y = _snap_point(payload.x_mm, payload.y_mm, payload.snap_to_grid)
        snap_note = _snap_notice((payload.x_mm, payload.y_mm), (target_x, target_y))
        def mutator(current: str) -> str:
            match = _find_placed_symbol_block(current, payload.reference)
            if match is None:
                raise ValueError(f"Reference '{payload.reference}' was not found in the schematic.")
            block, start, end, parsed = match
            shifted = _shift_symbol_block(
                block,
                dx_mm=target_x - float(parsed["x"]),
                dy_mm=target_y - float(parsed["y"]),
            )
            return current[:start] + shifted + current[end:]

        try:
            transactional_write(mutator)
        except ValueError as exc:
            return str(exc)

        result = _reload_schematic()
        lines = [
            result,
            f"Moved symbol '{payload.reference}' to ({target_x:.2f}, {target_y:.2f}) mm.",
        ]
        if snap_note:
            lines.append(snap_note)
        return "\n".join(lines)

    @mcp.tool()
    def sch_delete_wire(wire_id: str) -> str:
        """Remove a specific wire segment using its UUID or unique UUID prefix."""
        payload = DeleteWireInput(wire_id=wire_id)
        sch_file = _get_schematic_file()
        current = sch_file.read_text(encoding="utf-8", errors="ignore")
        wire_records = _extract_wires(current)
        matches = [
            wire
            for wire in wire_records
            if wire.get("uuid") and _wire_id_matches(str(wire["uuid"]), payload.wire_id)
        ]
        if not matches:
            return f"Wire '{payload.wire_id}' was not found in the active schematic."
        if len(matches) > 1:
            matching_ids = ", ".join(str(wire["uuid"]) for wire in matches[:5])
            return (
                f"Wire identifier '{payload.wire_id}' is ambiguous. "
                f"Matching UUIDs: {matching_ids}"
            )

        target = matches[0]
        target_signature = _wire_signature(
            target["x1"],
            target["y1"],
            target["x2"],
            target["y2"],
        )

        def mutator(current_text: str) -> str:
            pieces: list[str] = []
            cursor = 0
            last = 0
            removed = False
            while cursor < len(current_text):
                if current_text[cursor:].startswith("(wire"):
                    block, length = _extract_block(current_text, cursor)
                    parsed = _parse_wire_block(block) if block else None
                    if parsed is not None:
                        signature = _wire_signature(
                            parsed["x1"],
                            parsed["y1"],
                            parsed["x2"],
                            parsed["y2"],
                        )
                        parsed_uuid = str(parsed.get("uuid", ""))
                        if (
                            signature == target_signature
                            and parsed_uuid
                            and _wire_id_matches(parsed_uuid, str(target["uuid"]))
                        ):
                            pieces.append(current_text[last:cursor])
                            cursor += length
                            last = cursor
                            removed = True
                            continue
                cursor += 1
            pieces.append(current_text[last:])
            if not removed:
                raise ValueError(f"Wire '{payload.wire_id}' could not be removed.")
            return "".join(pieces)

        try:
            transactional_write(mutator)
        except ValueError as exc:
            return str(exc)
        return (
            f"{_reload_schematic()}\n"
            f"Deleted wire '{target['uuid']}' from "
            f"({_fmt_mm(target['x1'])}, {_fmt_mm(target['y1'])}) to "
            f"({_fmt_mm(target['x2'])}, {_fmt_mm(target['y2'])})."
        )

    @mcp.tool()
    def sch_delete_symbol(reference: str) -> str:
        """Remove a placed symbol and any directly attached wire segments."""
        payload = DeleteSymbolInput(reference=reference)
        removed_wire_count = 0
        removed_symbol_count = 0

        def mutator(current: str) -> str:
            nonlocal removed_symbol_count, removed_wire_count

            matches = _find_placed_symbol_blocks(current, payload.reference)
            if not matches:
                raise ValueError(f"Reference '{payload.reference}' was not found in the schematic.")
            removed_symbol_count = len(matches)
            connection_points = {
                point
                for _, _, _, parsed in matches
                for point in _symbol_connection_points(parsed)
            }

            pieces: list[str] = []
            cursor = 0
            last = 0
            while cursor < len(current):
                if current[cursor:].startswith("(symbol"):
                    block, length = _extract_block(current, cursor)
                    parsed = _parse_symbol_block(block) if block else None
                    if parsed is not None and parsed["reference"] == payload.reference:
                        pieces.append(current[last:cursor])
                        cursor += length
                        last = cursor
                        continue
                if current[cursor:].startswith("(wire"):
                    block, length = _extract_block(current, cursor)
                    parsed_wire = _parse_wire_block(block) if block else None
                    if parsed_wire is not None:
                        start = _coord_pair_key(parsed_wire["x1"], parsed_wire["y1"])
                        end = _coord_pair_key(parsed_wire["x2"], parsed_wire["y2"])
                        if start in connection_points or end in connection_points:
                            removed_wire_count += 1
                            pieces.append(current[last:cursor])
                            cursor += length
                            last = cursor
                            continue
                cursor += 1
            pieces.append(current[last:])
            return "".join(pieces)

        try:
            transactional_write(mutator)
        except ValueError as exc:
            return str(exc)

        return (
            f"{_reload_schematic()}\n"
            f"Deleted {removed_symbol_count} symbol block(s) for '{payload.reference}' "
            f"and {removed_wire_count} directly connected wire(s)."
        )

    @mcp.tool()
    def sch_analyze_net_compilation(
        symbols: list[dict[str, Any]] | None = None,
        wires: list[dict[str, Any]] | None = None,
        labels: list[dict[str, Any]] | None = None,
        power_symbols: list[dict[str, Any]] | None = None,
        nets: list[dict[str, Any]] | None = None,
        snap_to_grid: bool = True,
        auto_layout: bool = False,
    ) -> str:
        """Preview how netlist-aware schematic compilation will resolve endpoints and wires."""
        (
            validated_symbols,
            validated_powers,
            validated_labels,
            validated_wires,
            raw_nets,
            generated_wires,
            unresolved_nets,
            resolution_stats,
        ) = _prepare_build_circuit_inputs(
            symbols=symbols,
            wires=wires,
            labels=labels,
            power_symbols=power_symbols,
            nets=nets,
            snap_to_grid=snap_to_grid,
            auto_layout=auto_layout,
        )
        return _render_net_compilation_report(
            symbols=validated_symbols,
            powers=validated_powers,
            labels=validated_labels,
            explicit_wires=len(validated_wires) - len(generated_wires),
            nets=raw_nets,
            generated_wires=generated_wires,
            unresolved_nets=unresolved_nets,
            resolution_stats=resolution_stats,
            auto_layout=auto_layout,
        )

    @mcp.tool()
    def sch_build_circuit(
        symbols: list[dict[str, Any]] | None = None,
        wires: list[dict[str, Any]] | None = None,
        labels: list[dict[str, Any]] | None = None,
        power_symbols: list[dict[str, Any]] | None = None,
        nets: list[dict[str, Any]] | None = None,
        snap_to_grid: bool = True,
        auto_layout: bool = False,
        ) -> str:
        """Build (overwrite) the active schematic from structured symbol, wire, and label inputs.

        IMPORTANT: This tool **replaces** the entire schematic content.  Any symbols
        already placed in the schematic will be lost.  To add symbols to an existing
        schematic without erasing it use ``sch_add_symbol`` / ``sch_add_wire`` /
        ``sch_add_label`` instead.

        Coordinates are snapped to the 2.54 mm grid by default.  When no coordinates
        are provided for a symbol, set ``auto_layout=True`` so the placement engine
        assigns non-overlapping positions automatically.  If nets are also provided
        the layout is connection-aware and generates Manhattan wire segments from
        symbol pins.  Nets that cannot resolve to at least two routable endpoints
        raise a clear error instead of silently producing a disconnected schematic.

        Recommended workflow:
          1. Call ``sch_find_free_placement(count=N)`` to obtain safe coordinates.
          2. Pass those coordinates in the ``symbols`` list.
          3. OR set ``auto_layout=True`` and omit coordinates entirely.
        """
        (
            validated_symbols,
            validated_powers,
            validated_labels,
            validated_wires,
            raw_nets,
            generated_wires,
            unresolved_nets,
            resolution_stats,
        ) = _prepare_build_circuit_inputs(
            symbols=symbols,
            wires=wires,
            labels=labels,
            power_symbols=power_symbols,
            nets=nets,
            snap_to_grid=snap_to_grid,
            auto_layout=auto_layout,
        )
        if unresolved_nets:
            logger.warning(
                "schematic_netlist_routing_incomplete",
                generated_wire_count=len(generated_wires),
                unresolved_net_count=len(unresolved_nets),
                unresolved_nets=unresolved_nets[:10],
            )
        if raw_nets and not generated_wires and not validated_wires:
            examples = "; ".join(
                (
                    f"{item['name']} "
                    f"(resolved {item['resolved_count']}/{item['endpoint_count']}, "
                    f"missing: {', '.join(item['unresolved_endpoints']) or 'all'})"
                )
                for item in unresolved_nets[:5]
            )
            raise ValueError(
                "Netlist-aware auto-layout could not generate any wire segments. "
                "The provided nets did not resolve to at least two routable endpoints. "
                "Use `sch_analyze_net_compilation()` to inspect unresolved nets, or "
                "provide explicit reference+pin endpoints / explicit wires. "
                f"Examples: {examples or 'no endpoints were routable'}. "
                f"Alias matches: {resolution_stats['pin_alias_resolutions']}."
            )

        root_uuid = new_uuid()
        cfg = get_config()
        project_name = cfg.project_file.stem if cfg.project_file is not None else "KiCadMCP"
        lib_defs_added: set[str] = set()
        lib_symbols_content: list[str] = []
        elements: list[str] = []

        # Load lib_symbols for regular symbols
        for sym in validated_symbols:
            key = f"{sym.library}:{sym.symbol_name}"
            if key not in lib_defs_added:
                lib_def = load_lib_symbol(sym.library, sym.symbol_name)
                if lib_def is not None:
                    lib_symbols_content.append(lib_def)
                lib_defs_added.add(key)

        # Load lib_symbols for power symbols
        for pwr in validated_powers:
            key = f"power:{pwr.name}"
            if key not in lib_defs_added:
                lib_def = load_lib_symbol("power", pwr.name)
                if lib_def is not None:
                    lib_symbols_content.append(lib_def)
                lib_defs_added.add(key)

        for sym in validated_symbols:
            symbol_x, symbol_y = _snap_point(
                sym.x_mm,
                sym.y_mm,
                snap_to_grid and sym.snap_to_grid,
            )
            elements.append(
                place_symbol_block(
                    lib_id=f"{sym.library}:{sym.symbol_name}",
                    x=symbol_x,
                    y=symbol_y,
                    reference=sym.reference,
                    value=sym.value,
                    footprint=sym.footprint,
                    rotation=sym.rotation,
                    unit=sym.unit,
                    project_name=project_name,
                    root_uuid=root_uuid,
                )
            )

        for index, pwr in enumerate(validated_powers, start=1):
            power_x, power_y = _snap_point(
                pwr.x_mm,
                pwr.y_mm,
                snap_to_grid and pwr.snap_to_grid,
            )
            elements.append(
                place_symbol_block(
                    lib_id=f"power:{pwr.name}",
                    x=power_x,
                    y=power_y,
                    reference=f"#PWR{index:03d}",
                    value=pwr.name,
                    rotation=pwr.rotation,
                    project_name=project_name,
                    root_uuid=root_uuid,
                )
            )

        for wire in validated_wires:
            elements.append(
                wire_block(
                    *_snap_line(
                        wire.x1_mm,
                        wire.y1_mm,
                        wire.x2_mm,
                        wire.y2_mm,
                        snap_to_grid and wire.snap_to_grid,
                    )
                )
            )

        for lbl in validated_labels:
            label_x, label_y = _snap_point(
                lbl.x_mm,
                lbl.y_mm,
                snap_to_grid and lbl.snap_to_grid,
            )
            elements.append(label_block(lbl.name, label_x, label_y, lbl.rotation))

        lib_section = "\t(lib_symbols\n"
        for lib_symbol in lib_symbols_content:
            lib_section += "\n".join("\t" + line for line in lib_symbol.splitlines()) + "\n"
        lib_section += "\t)"
        content = (
            "(kicad_sch\n"
            "\t(version 20250316)\n"
            '\t(generator "kicad-mcp-pro")\n'
            f'\t(uuid "{root_uuid}")\n'
            '\t(paper "A4")\n'
            f"{lib_section}\n"
            + "\n".join(elements)
            + (
                "\n\t(sheet_instances\n"
                '\t\t(path "/"\n'
                '\t\t\t(page "1")\n'
                "\t\t)\n"
                "\t)\n"
                "\t(embedded_fonts no)\n"
                ")\n"
            )
        )
        content = _normalize_schematic_wire_connectivity(content)
        _validate_schematic_text(content)
        _get_schematic_file().write_text(content, encoding="utf-8")
        result = _reload_schematic()
        if auto_layout and raw_nets:
            return (
                f"{result}\nApplied netlist-aware auto-layout and generated "
                f"{len(generated_wires)} wire segment(s)."
            )
        if auto_layout:
            return f"{result}\nApplied basic auto-layout to schematic symbols."
        return result

    @mcp.tool()
    def sch_get_pin_positions(
        library: str,
        symbol_name: str,
        x_mm: float,
        y_mm: float,
        rotation: int = 0,
        unit: int = 1,
    ) -> str:
        """Calculate absolute pin positions for a given symbol placement."""
        available_units = get_symbol_available_units(library, symbol_name)
        if available_units and unit not in available_units:
            return (
                f"{library}:{symbol_name} does not support unit {unit}. "
                f"Available units: {_format_available_units(available_units)}."
            )

        positions = get_pin_positions(library, symbol_name, x_mm, y_mm, rotation, unit)
        if not positions:
            return f"Could not calculate pin positions for {library}:{symbol_name}."
        lines = [f"{library}:{symbol_name} @ ({x_mm}, {y_mm}) rot={rotation} unit={unit}:"]
        for pin, coords in sorted(positions.items()):
            lines.append(f"- Pin {pin}: ({coords[0]:.4f}, {coords[1]:.4f}) mm")
        return "\n".join(lines)

    @mcp.tool()
    def sch_check_power_flags() -> str:
        """Check whether common power nets appear to be flagged."""
        data = parse_schematic_file(_get_schematic_file())
        named_power = {
            label["name"]
            for label in data["labels"]
            if label["name"].upper() in {"GND", "VCC", "+3V3", "+5V", "+12V"}
        }
        power_symbols = {symbol["value"].upper() for symbol in data["power_symbols"]}
        missing = sorted(name for name in named_power if name.upper() not in power_symbols)
        if not missing:
            return "No obvious missing power flags were detected."
        return "Potential missing power flags:\n" + "\n".join(f"- {name}" for name in missing)

    @mcp.tool()
    def sch_annotate(start_number: int = 1, order: str = "alpha") -> str:
        """Renumber schematic references sequentially."""
        payload = AnnotateInput(start_number=start_number, order=order)
        data = parse_schematic_file(_get_schematic_file())
        symbols = list(data["symbols"])
        if payload.order == "sheet":
            symbols.sort(key=lambda item: (item["y"], item["x"]))
        else:
            symbols.sort(key=lambda item: item["reference"])

        counters: dict[str, int] = {}
        updates: list[tuple[str, str]] = []
        for symbol in symbols:
            prefix_match = re.match(r"([A-Za-z#]+)", symbol["reference"])
            prefix = prefix_match.group(1) if prefix_match else "U"
            counters.setdefault(prefix, payload.start_number)
            new_reference = f"{prefix}{counters[prefix]}"
            counters[prefix] += 1
            updates.append((symbol["reference"], new_reference))

        def mutator(current: str) -> str:
            updated = current
            for old_reference, new_reference in updates:
                updated = updated.replace(
                    f'(property "Reference" "{old_reference}"',
                    f'(property "Reference" "{new_reference}"',
                    1,
                )
            return updated

        transactional_write(mutator)
        return f"Annotated {len(updates)} symbol(s).\n{_reload_schematic()}"

    @mcp.tool()
    def sch_reload() -> str:
        """Ask KiCad to reload the active schematic."""
        return _reload_schematic()

    @mcp.tool()
    def sch_create_sheet(
        name: str,
        filename: str,
        x_mm: float,
        y_mm: float,
        snap_to_grid: bool = True,
    ) -> str:
        """Create a child schematic sheet and add it to the active top-level schematic."""
        payload = CreateSheetInput(
            name=name,
            filename=filename,
            x_mm=x_mm,
            y_mm=y_mm,
            snap_to_grid=snap_to_grid,
        )
        try:
            from kicad_sch_api import create_schematic
        except Exception as exc:
            logger.warning("schematic_create_sheet_dependency_missing", error=str(exc))
            return "kicad-sch-api is unavailable, so child sheet creation could not run."

        top_schematic_path = _get_schematic_file()
        sheet_x, sheet_y = _snap_point(payload.x_mm, payload.y_mm, payload.snap_to_grid)
        snap_note = _snap_notice((payload.x_mm, payload.y_mm), (sheet_x, sheet_y))
        child_name = payload.filename
        if not child_name.endswith(".kicad_sch"):
            child_name = f"{child_name}.kicad_sch"
        child_path = top_schematic_path.parent / child_name
        child_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            schematic = _load_kicad_schematic(top_schematic_path)
            if schematic.sheets.get_sheet_by_name(payload.name) is not None:
                return f"Sheet '{payload.name}' already exists."
            if not child_path.exists():
                child_schematic = create_schematic(payload.name)
                child_schematic.save(child_path, preserve_format=True)
            schematic.add_sheet(
                payload.name,
                str(child_path.relative_to(top_schematic_path.parent)).replace("\\", "/"),
                (sheet_x, sheet_y),
                (DEFAULT_SHEET_WIDTH_MM, DEFAULT_SHEET_HEIGHT_MM),
                project_name=_project_name(),
            )
            schematic.save(top_schematic_path, preserve_format=True)
        except Exception as exc:
            logger.warning(
                "schematic_create_sheet_failed",
                name=payload.name,
                filename=str(child_path),
                error=str(exc),
            )
            return f"Could not create child sheet '{payload.name}': {exc}"

        result = _reload_schematic()
        detail = f"Created child sheet '{payload.name}' -> {child_path.name}."
        if snap_note:
            detail = f"{detail}\n{snap_note}"
        return f"{result}\n{detail}"

    @mcp.tool()
    def sch_add_hierarchical_label(
        text: str,
        x_mm: float,
        y_mm: float,
        shape: str = "input",
        rotation: int = 0,
        snap_to_grid: bool = True,
    ) -> str:
        """Add a hierarchical label, preserving the requested shape and rotation."""
        payload = HierarchicalLabelInput(
            text=text,
            x_mm=x_mm,
            y_mm=y_mm,
            shape=shape,
            rotation=rotation,
            snap_to_grid=snap_to_grid,
        )
        label_x, label_y = _snap_point(payload.x_mm, payload.y_mm, payload.snap_to_grid)
        snap_note = _snap_notice((payload.x_mm, payload.y_mm), (label_x, label_y))
        transactional_write(
            lambda current: _append_before_sheet_instances(
                current,
                label_block(
                    payload.text,
                    label_x,
                    label_y,
                    payload.rotation,
                    kind="hierarchical_label",
                    shape=payload.shape,
                ),
            )
        )
        result = _reload_schematic()
        return f"{result}\n{snap_note}" if snap_note else result

    @mcp.tool()
    def sch_add_global_label(
        text: str,
        x_mm: float,
        y_mm: float,
        shape: str = "bidirectional",
        rotation: int = 0,
        snap_to_grid: bool = True,
    ) -> str:
        """Add a global label, preserving the requested shape and rotation."""
        payload = GlobalLabelInput(
            text=text,
            x_mm=x_mm,
            y_mm=y_mm,
            shape=shape,
            rotation=rotation,
            snap_to_grid=snap_to_grid,
        )
        label_x, label_y = _snap_point(payload.x_mm, payload.y_mm, payload.snap_to_grid)
        snap_note = _snap_notice((payload.x_mm, payload.y_mm), (label_x, label_y))
        transactional_write(
            lambda current: _append_before_sheet_instances(
                current,
                label_block(
                    payload.text,
                    label_x,
                    label_y,
                    payload.rotation,
                    kind="global_label",
                    shape=payload.shape,
                ),
            )
        )
        result = _reload_schematic()
        return f"{result}\n{snap_note}" if snap_note else result

    @mcp.tool()
    def sch_list_sheets() -> str:
        """List child sheets from the active top-level schematic."""
        sch_file = _get_schematic_file()
        try:
            schematic = _load_kicad_schematic(sch_file)
            hierarchy = schematic.sheets.get_sheet_hierarchy()
        except Exception as exc:
            logger.warning(
                "schematic_list_sheets_failed",
                schematic_file=str(sch_file),
                error=str(exc),
            )
            return f"Could not inspect sheet hierarchy: {exc}"

        children = hierarchy.get("root", {}).get("children", [])
        if not children:
            return "The active schematic has no child sheets."

        lines = [f"Child sheets ({len(children)} total):"]
        for child in children:
            position = child.get("position")
            size = child.get("size")
            lines.append(
                f"- {child.get('name')} -> {child.get('filename')} "
                f"@ ({float(position.x):.2f}, {float(position.y):.2f}) "
                f"size=({float(size.x):.2f}, {float(size.y):.2f})"
            )
        return "\n".join(lines)

    @mcp.tool()
    def sch_get_sheet_info(sheet_name: str) -> str:
        """Return metadata for a specific child sheet."""
        payload = GetSheetInfoInput(sheet_name=sheet_name)
        sch_file = _get_schematic_file()
        try:
            schematic = _load_kicad_schematic(sch_file)
            info = schematic.sheets.get_sheet_by_name(payload.sheet_name)
        except Exception as exc:
            logger.warning(
                "schematic_get_sheet_info_failed",
                schematic_file=str(sch_file),
                sheet_name=payload.sheet_name,
                error=str(exc),
            )
            return f"Could not inspect sheet '{payload.sheet_name}': {exc}"

        if info is None:
            return f"Sheet '{payload.sheet_name}' was not found."

        pins = info.get("pins", [])
        position = info.get("position", {})
        size = info.get("size", {})
        lines = [f"Sheet '{payload.sheet_name}'"]
        lines.append(f"- File: {info.get('filename')}")
        lines.append(
            "- Position: "
            f"({float(position.get('x', 0.0)):.2f}, {float(position.get('y', 0.0)):.2f}) mm"
        )
        lines.append(
            "- Size: "
            f"({float(size.get('width', 0.0)):.2f}, {float(size.get('height', 0.0)):.2f}) mm"
        )
        lines.append(f"- Page: {info.get('page_number', '?')}")
        lines.append(f"- Pins: {len(pins)}")
        return "\n".join(lines)

    @mcp.tool()
    def sch_route_wire_between_pins(
        ref1: str,
        pin1: str,
        ref2: str,
        pin2: str,
        snap_to_grid: bool = True,
    ) -> str:
        """Route deterministic Manhattan wire segments between two placed symbol pins."""
        payload = RouteWireBetweenPinsInput(
            ref1=ref1,
            pin1=pin1,
            ref2=ref2,
            pin2=pin2,
            snap_to_grid=snap_to_grid,
        )
        data = parse_schematic_file(_get_schematic_file())
        symbols = {symbol["reference"]: symbol for symbol in data["symbols"]}
        first = symbols.get(payload.ref1)
        second = symbols.get(payload.ref2)
        if first is None:
            return f"Reference '{payload.ref1}' was not found in the schematic."
        if second is None:
            return f"Reference '{payload.ref2}' was not found in the schematic."

        first_library, first_symbol = _split_lib_id(str(first["lib_id"]))
        second_library, second_symbol = _split_lib_id(str(second["lib_id"]))
        first_pins = get_pin_positions(
            first_library,
            first_symbol,
            float(first["x"]),
            float(first["y"]),
            int(first["rotation"]),
            int(first["unit"]),
        )
        second_pins = get_pin_positions(
            second_library,
            second_symbol,
            float(second["x"]),
            float(second["y"]),
            int(second["rotation"]),
            int(second["unit"]),
        )
        start = first_pins.get(payload.pin1)
        end = second_pins.get(payload.pin2)
        if start is None:
            return f"Pin {payload.pin1} was not found on {payload.ref1}."
        if end is None:
            return f"Pin {payload.pin2} was not found on {payload.ref2}."

        content = _get_schematic_file().read_text(encoding="utf-8", errors="ignore")
        obstacles = _get_symbol_bboxes(content)
        segments, routing_warning = _route_avoiding_obstacles(
            start,
            end,
            obstacles,
            payload.snap_to_grid,
        )
        if not segments:
            return (
                f"{payload.ref1}:{payload.pin1} and {payload.ref2}:{payload.pin2} "
                "already overlap."
            )

        def mutator(current: str) -> str:
            updated = current
            for segment in segments:
                updated = _append_before_sheet_instances(updated, wire_block(*segment))
            return updated

        transactional_write(mutator)
        result = _reload_schematic()
        return (
            f"{result}\nRouted {len(segments)} wire segment(s) between "
            f"{payload.ref1}:{payload.pin1} and {payload.ref2}:{payload.pin2}."
            + (f"\n{routing_warning}" if routing_warning else "")
        )

    @mcp.tool()
    @headless_compatible
    def sch_add_missing_junctions() -> str:
        """Insert missing schematic junctions at T-intersection wire endpoints."""
        summary = run_auto_add_missing_junctions()
        result = _reload_schematic()
        return f"{result}\n{summary}"

    @mcp.tool()
    def sch_get_connectivity_graph() -> str:
        """Summarize the active schematic as a textual net connectivity graph."""
        groups = _build_connectivity_groups(_get_schematic_file())
        if not groups:
            return "The active schematic has no connectivity to summarize."

        lines = [f"Connectivity groups ({len(groups)} total):"]
        for index, group in enumerate(groups, start=1):
            names = ", ".join(group["names"]) if group["names"] else "~unnamed"
            pins = ", ".join(
                f"{item['reference']}:{item['pin']}" for item in group["pins"]
            ) or "none"
            lines.append(
                f"- Group {index}: {names} | pins={pins} | points={len(group['points'])}"
            )
        return "\n".join(lines)

    @mcp.tool()
    def sch_trace_net(net_name: str) -> str:
        """Trace a named net through the active schematic and matching child sheets."""
        payload = TraceNetInput(net_name=net_name)
        target = payload.net_name
        local_matches = [
            group
            for group in _build_connectivity_groups(_get_schematic_file())
            if target in group["names"]
        ]

        child_matches: list[str] = []
        for display_name, child_path in _iter_child_sheet_paths(_get_schematic_file()):
            if not child_path.exists():
                continue
            child_data = parse_schematic_file(child_path)
            matched_labels = [
                label
                for label in child_data["labels"]
                if str(label["name"]) == target
            ]
            matched_power = [
                symbol
                for symbol in child_data["power_symbols"]
                if str(symbol["value"]) == target
            ]
            if matched_labels or matched_power:
                child_matches.append(
                    f"- {display_name}: labels={len(matched_labels)} "
                    f"power_symbols={len(matched_power)}"
                )

        if not local_matches and not child_matches:
            return f"Net '{target}' was not found in the active schematic or child sheets."

        lines = [f"Trace for net '{target}':"]
        if local_matches:
            for index, group in enumerate(local_matches, start=1):
                pins = ", ".join(
                    f"{item['reference']}:{item['pin']}" for item in group["pins"]
                ) or "none"
                lines.append(
                    f"- Top level match {index}: pins={pins} points={len(group['points'])}"
                )
        if child_matches:
            lines.append("Child sheet matches:")
            lines.extend(child_matches)
        return "\n".join(lines)

    @mcp.tool()
    def sch_auto_place_symbols(
        symbol_list: list[str] | None = None,
        strategy: str = "cluster",
    ) -> str:
        """Auto-place selected references using deterministic cluster, linear, or star layouts.

        Unlike the legacy behaviour, this version reads all already-placed symbols
        first and avoids placing new symbols on top of them.  Fixed/already-placed
        symbols that are not in ``symbol_list`` are treated as immovable obstacles.
        """
        payload = AutoPlaceSymbolsInput(symbol_list=symbol_list or [], strategy=strategy)
        sch_file = _get_schematic_file()
        try:
            schematic = _load_kicad_schematic(sch_file)
        except Exception as exc:
            logger.warning(
                "schematic_auto_place_load_failed",
                schematic_file=str(sch_file),
                error=str(exc),
            )
            return f"Could not load the active schematic for auto-placement: {exc}"

        sch_data = parse_schematic_file(sch_file)
        all_syms = sch_data["symbols"] + sch_data["power_symbols"]

        requested = payload.symbol_list or [
            str(sym["reference"]) for sym in sch_data["symbols"]
        ]
        if not requested:
            return "The active schematic contains no symbols to auto-place."

        requested_set = set(requested)

        # Symbols NOT being moved are fixed obstacles.
        fixed_syms = [s for s in all_syms if str(s.get("reference", "")) not in requested_set]
        occupied = _estimate_occupied_cells(fixed_syms)

        placed = 0
        missing: list[str] = []
        radius_mm = AUTO_LAYOUT_COLUMN_SPACING_MM * 2
        center_x = AUTO_LAYOUT_ORIGIN_X_MM + AUTO_LAYOUT_COLUMN_SPACING_MM
        center_y = AUTO_LAYOUT_ORIGIN_Y_MM + AUTO_LAYOUT_ROW_SPACING_MM

        for index, reference in enumerate(requested):
            component = schematic.components.get(reference)
            if component is None:
                missing.append(reference)
                continue

            if payload.strategy == "linear":
                # Find next free cell along a single row
                x, y = _next_free_cell(
                    occupied,
                    start_col=index,
                    start_row=0,
                    max_cols=24,
                )
            elif payload.strategy == "star":
                if index == 0:
                    x = center_x
                    y = center_y
                    # Mark centre cell occupied
                    col = int(round((x - AUTO_LAYOUT_ORIGIN_X_MM) / AUTO_LAYOUT_COLUMN_SPACING_MM))
                    row = int(round((y - AUTO_LAYOUT_ORIGIN_Y_MM) / AUTO_LAYOUT_ROW_SPACING_MM))
                    occupied.add((col, row))
                else:
                    angle = ((index - 1) / max(len(requested) - 1, 1)) * (2 * math.pi)
                    raw_x = center_x + (radius_mm * math.cos(angle))
                    raw_y = center_y + (radius_mm * math.sin(angle))
                    # Snap to nearest free cell
                    col = int(
                        round((raw_x - AUTO_LAYOUT_ORIGIN_X_MM) / AUTO_LAYOUT_COLUMN_SPACING_MM)
                    )
                    row = int(round((raw_y - AUTO_LAYOUT_ORIGIN_Y_MM) / AUTO_LAYOUT_ROW_SPACING_MM))
                    x, y = _next_free_cell(occupied, start_col=col, start_row=row)
            else:
                # cluster: row-major grid, skip occupied cells
                x, y = _next_free_cell(occupied)

            snapped_x, snapped_y = _snap_point(x, y, True)
            component.move(snapped_x, snapped_y)
            placed += 1

        try:
            schematic.save(sch_file, preserve_format=True)
        except Exception as exc:
            logger.warning(
                "schematic_auto_place_save_failed",
                schematic_file=str(sch_file),
                error=str(exc),
            )
            return f"Could not save auto-placement changes: {exc}"

        result = _reload_schematic()
        missing_suffix = f" Missing: {', '.join(missing)}." if missing else ""
        return (
            f"{result}\n"
            f"Auto-placed {placed} symbol(s) using the {payload.strategy} strategy. "
            f"Overlap-aware placement respected {len(fixed_syms)} fixed obstacle(s)."
            f"{missing_suffix}"
        )

    # -----------------------------------------------------------------------
    # Spatial awareness tools (v2.1.0)
    # -----------------------------------------------------------------------

    @mcp.tool()
    @headless_compatible
    def sch_get_bounding_boxes() -> str:
        """Return the estimated bounding box of every symbol in the active schematic.

        Use this before calling sch_add_symbol or sch_build_circuit to understand
        which areas of the schematic sheet are already occupied.  The bounding boxes
        are heuristic estimates (KiCad does not expose exact extents via the file API)
        but are conservative enough to avoid overlap in practice.

        Returns:
            A table of all symbols with their centre position and estimated
            bounding-box corners (x_min, y_min, x_max, y_max) in mm, plus an
            occupied-area summary.
        """
        sch_file = _get_schematic_file()
        sch_data = parse_schematic_file(sch_file)
        all_syms = sch_data["symbols"] + sch_data["power_symbols"]

        if not all_syms:
            return "The active schematic contains no symbols."

        lines = [
            f"Schematic bounding boxes ({len(all_syms)} symbols):",
            (
                f"{'Ref':<10} {'Value':<16} {'X':>8} {'Y':>8} "
                f"{'X_min':>8} {'Y_min':>8} {'X_max':>8} {'Y_max':>8}"
            ),
            "-" * 76,
        ]
        extents: list[tuple[float, float, float, float]] = []
        for sym in all_syms:
            ref = str(sym.get("reference", "?"))
            val = str(sym.get("value", ""))[:16]
            x = float(sym.get("x", sym.get("x_mm", 0.0)) or 0.0)
            y = float(sym.get("y", sym.get("y_mm", 0.0)) or 0.0)
            x_min, y_min, x_max, y_max = _symbol_bbox_bounds(sym)
            extents.append((x_min, y_min, x_max, y_max))
            lines.append(
                f"{ref:<10} {val:<16} {x:>8.2f} {y:>8.2f} "
                f"{x_min:>8.2f} {y_min:>8.2f} {x_max:>8.2f} {y_max:>8.2f}"
            )

        if extents:
            lines += [
                "",
                f"Sheet occupied region: X=[{min(item[0] for item in extents):.1f}, "
                f"{max(item[2] for item in extents):.1f}] "
                f"Y=[{min(item[1] for item in extents):.1f}, "
                f"{max(item[3] for item in extents):.1f}] mm",
                "Tip: use sch_find_free_placement to get safe coordinates for new symbols.",
            ]

        return "\n".join(lines)

    @mcp.tool()
    @headless_compatible
    def sch_find_free_placement(
        count: int = 1,
        cell_width_mm: float = AUTO_LAYOUT_COLUMN_SPACING_MM,
        cell_height_mm: float = AUTO_LAYOUT_ROW_SPACING_MM,
        keepout_regions: list[tuple[float, float, float, float]] | None = None,
    ) -> str:
        """Find N collision-free placement coordinates for new symbols.

        Reads the current schematic, builds an occupancy grid from all existing
        symbols, and returns ``count`` coordinate pairs that do not overlap with
        any placed symbol.  Call this before sch_add_symbol to get safe (x, y)
        values.

        Args:
            count: Number of free coordinate slots to return (default 1, max 64).
            cell_width_mm: Grid cell width in mm (default 25.4 — one 10-mil grid unit).
            cell_height_mm: Grid cell height in mm (default 17.78).
            keepout_regions: Optional rectangular keepouts as
                ``[(x_min, y_min, x_max, y_max), ...]`` in mm.

        Returns:
            A list of (x_mm, y_mm) coordinate pairs, one per requested slot.
        """
        count = max(1, min(count, 64))
        sch_file = _get_schematic_file()
        sch_data = parse_schematic_file(sch_file)
        all_syms = sch_data["symbols"] + sch_data["power_symbols"]

        occupied = _estimate_occupied_cells(all_syms, cell_w=cell_width_mm, cell_h=cell_height_mm)
        keepouts = keepout_regions or []
        if keepouts:
            occupied.update(
                _keepout_occupied_cells(
                    keepouts,
                    cell_w=cell_width_mm,
                    cell_h=cell_height_mm,
                )
            )

        coords: list[tuple[float, float]] = []
        for _ in range(count):
            x, y = _next_free_cell(
                occupied,
                cell_w=cell_width_mm,
                cell_h=cell_height_mm,
            )
            coords.append((round(x, 4), round(y, 4)))

        lines = [
            f"Free placement coordinates ({count} slot(s) requested, "
            f"{len(all_syms)} existing symbol(s) avoided, "
            f"{len(keepouts)} keepout region(s) respected):",
        ]
        for i, (x, y) in enumerate(coords, start=1):
            lines.append(f"  Slot {i}: x_mm={x}, y_mm={y}")
        lines.append(
            "\nPass these coordinates directly to sch_add_symbol(x_mm=..., y_mm=...)."
        )
        return "\n".join(lines)

    @mcp.tool()
    @headless_compatible
    def sch_set_sheet_size(
        paper: str = "A3",
    ) -> str:
        """Change the schematic sheet (paper) size.

        Use this when the current sheet is too small to fit all symbols — for
        example after ``sch_auto_place_functional`` warns that symbols were
        placed outside the sheet boundary, or when you receive a screenshot
        showing components outside the red sheet border.

        Supported sizes (landscape): A4, A3, A2, A1, A0, A (letter), B, C, D, E,
        USLetter, USLegal.

        After resizing you should call ``sch_auto_place_functional`` again so
        that symbols are re-distributed across the larger sheet.

        Args:
            paper: Target paper size keyword (default "A3").

        Returns:
            Confirmation with old and new dimensions.
        """
        paper = paper.strip()
        if paper not in PAPER_SIZES_MM:
            available = ", ".join(sorted(PAPER_SIZES_MM))
            return (
                f"Unknown paper size '{paper}'. "
                f"Available sizes: {available}."
            )

        sch_file = _get_schematic_file()
        try:
            text = sch_file.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            return f"Could not read schematic file: {exc}"

        # Find existing paper declaration
        old_paper = _read_sheet_paper(sch_file)
        old_w, old_h = PAPER_SIZES_MM.get(old_paper, (0.0, 0.0))
        new_w, new_h = PAPER_SIZES_MM[paper]

        # Replace or insert paper line
        if re.search(r'\(paper\s+"[^"]*"', text):
            new_text = re.sub(
                r'\(paper\s+"[^"]*"\)',
                f'(paper "{paper}")',
                text,
            )
        else:
            # Insert after the kicad_sch opening tag
            new_text = re.sub(
                r'(\(kicad_sch[^\n]*\n)',
                rf'\1  (paper "{paper}")\n',
                text,
                count=1,
            )

        if new_text == text:
            return (
                f"Sheet is already '{paper}' ({new_w:.0f} x {new_h:.0f} mm). No change made."
            )

        try:
            sch_file.write_text(new_text, encoding="utf-8")
        except Exception as exc:
            return f"Could not write schematic file: {exc}"

        result = _reload_schematic()
        usable_cols = _sheet_usable_cols(paper)
        usable_rows = _sheet_usable_rows(paper)
        return (
            f"{result}\n"
            f"Sheet resized: {old_paper} ({old_w:.0f}x{old_h:.0f} mm) "
            f"-> {paper} ({new_w:.0f}x{new_h:.0f} mm).\n"
            f"Usable grid: {usable_cols} columns x {usable_rows} rows "
            f"(origin {AUTO_LAYOUT_ORIGIN_X_MM} mm, margin {_SHEET_MARGIN_MM} mm).\n"
            f"Tip: run sch_auto_place_functional to redistribute symbols on the new sheet."
        )

    @mcp.tool()
    @headless_compatible
    def sch_auto_resize_sheet() -> str:
        """Automatically grow the sheet to fit all currently placed symbols.

        Reads the bounding box of all placed symbols and selects the smallest
        standard paper size (A4 → A3 → A2 → A1) that contains them with the
        configured margin.  If the current sheet already fits, reports that no
        change is needed.

        Returns:
            The chosen paper size and new dimensions, or a message if the
            current size is already sufficient.
        """
        sch_file = _get_schematic_file()
        sch_data = parse_schematic_file(sch_file)
        all_syms = sch_data["symbols"] + sch_data["power_symbols"]

        if not all_syms:
            return "No symbols found — sheet size unchanged."

        xs = [float(s.get("x", s.get("x_mm", 0.0)) or 0.0) for s in all_syms]
        ys = [float(s.get("y", s.get("y_mm", 0.0)) or 0.0) for s in all_syms]

        required_w = max(xs) + _SYMBOL_HALF_W_MM + _SHEET_MARGIN_MM
        required_h = max(ys) + _SYMBOL_HALF_H_MM + _SHEET_MARGIN_MM

        # Pick smallest standard size (in landscape) that fits
        candidates = ["A4", "A3", "A2", "A1", "A0", "B", "C", "D", "E"]
        chosen = None
        for size in candidates:
            w, h = PAPER_SIZES_MM[size]
            if w >= required_w and h >= required_h:
                chosen = size
                break

        current_paper = _read_sheet_paper(sch_file)
        cur_w, cur_h = PAPER_SIZES_MM.get(current_paper, PAPER_SIZES_MM["A4"])

        if chosen is None:
            return (
                f"Symbols span {required_w:.0f} x {required_h:.0f} mm — "
                "no standard size is large enough.  Consider splitting into "
                "hierarchical sheets (sch_create_sheet)."
            )

        if chosen == current_paper:
            return (
                f"Current sheet '{current_paper}' ({cur_w:.0f}x{cur_h:.0f} mm) "
                f"already fits all symbols (required {required_w:.0f}x{required_h:.0f} mm)."
            )

        # Delegate to sch_set_sheet_size logic
        return str(sch_set_sheet_size(paper=chosen))

    @mcp.tool()
    @headless_compatible
    def sch_auto_place_functional(
        symbol_list: list[str] | None = None,
        anchor_ref: str | list[str] | None = None,
    ) -> str:
        """Place schematic symbols into semantically meaningful zones on the sheet.

        Unlike the basic ``sch_auto_place_symbols`` which uses a plain grid,
        this tool categorises each symbol by its **function** (MCU, connector,
        power IC, sensor, passive, protection …) and places it in the
        corresponding region of the schematic sheet.  The result is a readable,
        professionally structured schematic with logical signal flow
        (connectors on the left, processing in the centre, power/decoupling at
        the bottom).

        Zone layout (column × row, each cell = 25.4 × 17.78 mm)::

            Col →    0-2          3-5          6-8
            Row 0:   connectors   MCU          UI/LED/SW
            Row 3:   power IC     sensors/IC   protection
            Row 5:   power_pass   passives     transistors/filter
            Row 7:   test points  ---          misc

        The actual sheet size is read from the schematic file.  If the symbol
        count would overflow the current sheet, a warning is appended
        recommending ``sch_auto_resize_sheet`` to switch to a larger format
        (A3, A2, …) before re-running this tool.

        Symbols already placed (not in ``symbol_list``) are treated as fixed
        obstacles and will not be overwritten.  Within each zone, symbols are
        arranged in a compact row-major sub-grid.

        Args:
            symbol_list: Optional list of reference designators to place.  If
                omitted, all symbols in the schematic are placed.
            anchor_ref: Optional single reference or list of references to keep
                fixed while re-placing the remaining symbols around them.

        Returns:
            A summary showing how many symbols were placed per functional zone,
            plus an overflow warning if the sheet is too small.
        """
        sch_file = _get_schematic_file()
        try:
            schematic = _load_kicad_schematic(sch_file)
        except Exception as exc:
            return f"Could not load the active schematic for functional placement: {exc}"

        sch_data = parse_schematic_file(sch_file)
        all_syms = sch_data["symbols"] + sch_data["power_symbols"]

        requested: list[str] = symbol_list or [
            str(s["reference"]) for s in sch_data["symbols"]
        ]
        if not requested:
            return "The active schematic contains no symbols to place."

        from .project import load_design_intent

        design_intent = load_design_intent()
        functional_spacing_mm = design_intent.functional_spacing_mm
        anchor_refs = _normalize_anchor_refs(anchor_ref)
        anchor_set = set(anchor_refs)

        requested_set = set(requested)
        paper = _read_sheet_paper(sch_file)
        max_cols = _sheet_usable_cols(paper)
        max_rows = _sheet_usable_rows(paper)
        sheet_w, sheet_h = PAPER_SIZES_MM.get(paper, PAPER_SIZES_MM["A4"])

        # Fixed obstacles — symbols we are NOT moving
        fixed_syms = [
            s
            for s in all_syms
            if str(s.get("reference", "")) not in requested_set
            or str(s.get("reference", "")) in anchor_set
        ]
        global_occupied = _estimate_occupied_cells(fixed_syms)

        # Per-zone occupancy
        zone_occupied: dict[str, set[tuple[int, int]]] = {
            z: set() for z in _FUNCTIONAL_ZONES
        }

        # Build symbol metadata lookup
        sym_meta: dict[str, dict[str, str]] = {}
        for s in sch_data["symbols"]:
            ref = str(s.get("reference", ""))
            sym_meta[ref] = {
                "value": str(s.get("value", "")),
                "lib_id": str(s.get("lib_id", "")),
            }

        anchored_preserved = [
            ref for ref in anchor_refs if ref in requested_set and schematic.components.get(ref)
        ]
        for symbol in fixed_syms:
            reference = str(symbol.get("reference", ""))
            category = _classify_symbol(
                ref=reference,
                value=sym_meta.get(reference, {}).get("value", ""),
                lib_id=sym_meta.get(reference, {}).get("lib_id", ""),
            )
            x = float(symbol.get("x", symbol.get("x_mm", 0.0)) or 0.0)
            y = float(symbol.get("y", symbol.get("y_mm", 0.0)) or 0.0)
            col = int(round((x - AUTO_LAYOUT_ORIGIN_X_MM) / AUTO_LAYOUT_COLUMN_SPACING_MM))
            row = int(round((y - AUTO_LAYOUT_ORIGIN_Y_MM) / AUTO_LAYOUT_ROW_SPACING_MM))
            zone_occupied.setdefault(category, set()).add((col, row))

        placed = 0
        overflow_count = 0
        missing: list[str] = []
        zone_counts: dict[str, int] = {}

        for reference in requested:
            if reference in anchor_set:
                continue
            component = schematic.components.get(reference)
            if component is None:
                missing.append(reference)
                continue

            meta = sym_meta.get(reference, {})
            category = _classify_symbol(
                ref=reference,
                value=meta.get("value", ""),
                lib_id=meta.get("lib_id", ""),
            )

            zone_col, zone_row = _functional_zone_origin(
                category,
                max_cols=max_cols,
                max_rows=max_rows,
                spacing_mm=functional_spacing_mm,
            )

            # Find next free cell within this zone's sub-grid
            placed_in_zone = zone_occupied[category]
            found = False
            for sub_row in range(0, max_rows):
                for sub_col in range(0, _ZONE_MAX_COLS):
                    cand_col = zone_col + sub_col
                    cand_row = zone_row + sub_row
                    if cand_col >= max_cols or cand_row >= max_rows:
                        continue
                    cell = (cand_col, cand_row)
                    if cell not in global_occupied and cell not in placed_in_zone:
                        col, row = cell
                        found = True
                        break
                if found:
                    break

            if not found:
                # Fall back to any remaining free cell within sheet bounds
                col_f, row_f = _next_free_cell(global_occupied, paper=paper)
                col = int(round((col_f - AUTO_LAYOUT_ORIGIN_X_MM) / AUTO_LAYOUT_COLUMN_SPACING_MM))
                row = int(round((row_f - AUTO_LAYOUT_ORIGIN_Y_MM) / AUTO_LAYOUT_ROW_SPACING_MM))
                # If still outside sheet bounds, flag overflow
                if col >= max_cols or row >= max_rows:
                    overflow_count += 1

            x = AUTO_LAYOUT_ORIGIN_X_MM + col * AUTO_LAYOUT_COLUMN_SPACING_MM
            y = AUTO_LAYOUT_ORIGIN_Y_MM + row * AUTO_LAYOUT_ROW_SPACING_MM
            snapped_x, snapped_y = _snap_point(x, y, True)

            component.move(snapped_x, snapped_y)
            placed += 1

            # Mark this cell occupied globally and within its zone
            for dc in (-1, 0, 1):
                for dr in (-1, 0, 1):
                    global_occupied.add((col + dc, row + dr))
            zone_occupied[category].add((col, row))
            zone_counts[category] = zone_counts.get(category, 0) + 1

        try:
            schematic.save(sch_file, preserve_format=True)
        except Exception as exc:
            return f"Could not save functional placement changes: {exc}"

        result = _reload_schematic()
        missing_suffix = f" Missing refs: {', '.join(missing)}." if missing else ""
        anchor_suffix = (
            f"\nAnchored refs preserved: {', '.join(anchored_preserved)}."
            if anchored_preserved
            else ""
        )

        zone_lines = [f"  {cat}: {n}" for cat, n in sorted(zone_counts.items())]
        summary = "\n".join(zone_lines) if zone_lines else "  (none)"

        overflow_note = ""
        if overflow_count:
            overflow_note = (
                f"\nWARNING: {overflow_count} symbol(s) could not fit within the "
                f"'{paper}' sheet ({sheet_w:.0f}x{sheet_h:.0f} mm).  "
                "Call sch_auto_resize_sheet to switch to a larger format, "
                "then run sch_auto_place_functional again."
            )

        return (
            f"{result}\n"
            f"Functional auto-placement complete on '{paper}' sheet — "
            f"{placed} symbol(s) placed in {len(zone_counts)} zone(s):\n{summary}"
            f"\nFunctional spacing target: {functional_spacing_mm:.2f} mm."
            f"{anchor_suffix}{missing_suffix}{overflow_note}"
        )

    # -----------------------------------------------------------------------
    # Subcircuit template tools (v2.1.0)
    # -----------------------------------------------------------------------

    @mcp.tool()
    @headless_compatible
    def sch_list_templates() -> str:
        """List all available reference subcircuit templates.

        Templates are pre-wired subcircuit blueprints for common building blocks
        (buck converter, LDO, USB Type-C, MCU decoupling, Ethernet with magnetics).

        Call sch_get_template_info() for full parameter and placement details,
        then sch_instantiate_template() to add the subcircuit to the schematic.
        """
        from pathlib import Path as _Path

        templates_dir = _Path(__file__).parent.parent / "templates" / "subcircuits"
        if not templates_dir.exists():
            return "No subcircuit templates are available."

        try:
            import yaml  # type: ignore[import-untyped]
        except ImportError:
            return "Template tools require PyYAML. Install it to inspect bundled templates."

        lines = ["# Available Subcircuit Templates", ""]
        for yaml_file in sorted(templates_dir.glob("*.yaml")):
            try:
                with yaml_file.open(encoding="utf-8") as fh:
                    data = yaml.safe_load(fh)
                name = data.get("name", yaml_file.stem)
                desc = str(data.get("description", "")).strip().split("\n")[0][:80]
                params = list(data.get("parameters", {}).keys())
                lines.append(f"**{name}**")
                lines.append(f"  {desc}")
                if params:
                    lines.append(f"  Parameters: {', '.join(params)}")
                lines.append("")
            except Exception:
                lines.append(f"**{yaml_file.stem}** — (could not parse template)")
                lines.append("")

        if len(lines) == 2:
            return "No subcircuit templates were found."

        lines.append("Use sch_instantiate_template(template_name, prefix, params) to add.")
        return "\n".join(lines)

    @mcp.tool()
    @headless_compatible
    def sch_get_template_info(template_name: str) -> str:
        """Return full details for a subcircuit template.

        Args:
            template_name: Template name as returned by sch_list_templates()
                (e.g. ``"buck_converter_generic"``).

        Returns:
            Structured template description including parameters, symbols,
            nets, and placement hints.
        """
        from pathlib import Path as _Path

        templates_dir = _Path(__file__).parent.parent / "templates" / "subcircuits"
        yaml_file = templates_dir / f"{template_name}.yaml"
        if not yaml_file.exists():
            available = [f.stem for f in templates_dir.glob("*.yaml")]
            return (
                f"Template '{template_name}' not found. "
                f"Available: {', '.join(sorted(available))}"
            )

        try:
            import yaml
            with yaml_file.open(encoding="utf-8") as fh:
                data = yaml.safe_load(fh)
        except ImportError:
            return "Template tools require PyYAML. Install it to inspect bundled templates."
        except Exception as exc:
            return f"Could not parse template '{template_name}': {exc}"

        lines = [
            f"# Template: {data.get('name', template_name)}",
            f"Version: {data.get('version', '1.0')}",
            "",
            data.get("description", "").strip(),
            "",
        ]

        params = data.get("parameters", {})
        if params:
            lines += ["## Parameters", ""]
            for pname, pdef in params.items():
                lines.append(
                    f"- **{pname}** ({pdef.get('type', 'any')}): "
                    f"{pdef.get('description', '')} "
                    f"[default: {pdef.get('default', '—')}]"
                )
            lines.append("")

        symbols = data.get("symbols", [])
        if symbols:
            lines += [f"## Symbols ({len(symbols)})", ""]
            for sym in symbols:
                lines.append(
                    f"- **{sym.get('ref_prefix', '?')}?** "
                    f"{sym.get('value', '?')} — {sym.get('comment', '')}"
                )
                left_pins = ", ".join(str(pin) for pin in sym.get("pins_left", []))
                right_pins = ", ".join(str(pin) for pin in sym.get("pins_right", []))
                pin_parts: list[str] = []
                if left_pins:
                    pin_parts.append(f"left: {left_pins}")
                if right_pins:
                    pin_parts.append(f"right: {right_pins}")
                if pin_parts:
                    lines.append(f"  Pins: {' | '.join(pin_parts)}")
            lines.append("")

        nets = data.get("nets", [])
        if nets:
            lines += ["## Nets", ""]
            for net in nets:
                note = f" — {net['note']}" if net.get("note") else ""
                lines.append(f"- `{net['name']}` ({net.get('type', 'signal')}){note}")
            lines.append("")

        hints = data.get("placement_hints", [])
        if hints:
            lines += ["## Placement Hints", ""]
            for hint in hints:
                lines.append(f"- {hint}")
            lines.append("")

        search = data.get("part_search_hints", {})
        if search:
            lines += ["## Part Search Hints (use with lib_recommend_part())", ""]
            for role, query in search.items():
                lines.append(f"- {role}: `{query}`")

        return "\n".join(lines)

    @mcp.tool()
    @headless_compatible
    def sch_instantiate_template(
        template_name: str,
        prefix: str = "",
        params: dict[str, object] | None = None,
    ) -> str:
        """Instantiate a subcircuit template — returns a structured action plan.

        This tool returns a structured plan describing the symbols, connections,
        and part-search steps needed to add the subcircuit to the schematic.
        It does NOT directly edit the schematic (use the plan as a guide for
        calling sch_add_symbol, sch_add_wire, lib_recommend_part, etc.).

        Args:
            template_name: Template name (from sch_list_templates()).
            prefix: Reference prefix applied to all template refs (e.g. ``"PWR_"``
                produces ``PWR_U1``, ``PWR_L1``, etc.).
            params: Dict of parameter overrides (e.g. ``{"vout_v": 5.0}``).

        Returns:
            Step-by-step instantiation plan in markdown format.
        """
        from pathlib import Path as _Path

        templates_dir = _Path(__file__).parent.parent / "templates" / "subcircuits"
        yaml_file = templates_dir / f"{template_name}.yaml"
        if not yaml_file.exists():
            available = [f.stem for f in templates_dir.glob("*.yaml")]
            return (
                f"Template '{template_name}' not found. "
                f"Available: {', '.join(sorted(available))}"
            )

        try:
            import yaml
            with yaml_file.open(encoding="utf-8") as fh:
                data = yaml.safe_load(fh)
        except ImportError:
            return "Template tools require PyYAML. Install it to instantiate templates."
        except Exception as exc:
            return f"Could not parse template '{template_name}': {exc}"

        params = params or {}
        defaults = {
            k: v.get("default") for k, v in data.get("parameters", {}).items()
        }
        resolved = {**defaults, **params}

        symbols = data.get("symbols", [])
        nets = data.get("nets", [])
        hints = data.get("placement_hints", [])
        search = data.get("part_search_hints", {})
        prefix_str = prefix.strip()

        lines = [
            f"# Instantiation Plan: {data.get('name', template_name)}",
            f"Prefix: `{prefix_str or '(none)'}`",
            "",
            "## Parameters",
        ]
        for k, v in resolved.items():
            lines.append(f"- {k}: **{v}**")

        lines += [
            "",
            "## Step 1: Add Symbols",
            "Call sch_add_symbol() for each symbol below:",
            "",
        ]
        for i, sym in enumerate(symbols, start=1):
            ref = f"{prefix_str}{sym.get('ref_prefix', 'X')}{i}"
            lines.append(
                f"- `sch_add_symbol(reference={ref!r}, value={sym.get('value', '?')!r})`"
            )
            lines.append(f"  Comment: {sym.get('comment', '')}")
            lines.append(f"  Footprint hint: {sym.get('default_footprint', '—')}")

        lines += [
            "",
            "## Step 2: Add Nets / Wires",
            "Call sch_add_power_symbol() and sch_add_wire() to connect:",
            "",
        ]
        for net in nets:
            note = f" ({net['note']})" if net.get("note") else ""
            lines.append(f"- `{net['name']}` — {net.get('type', 'signal')}{note}")

        lines += ["", "## Step 3: Part Selection"]
        if search:
            for role, query_template in search.items():
                query = str(query_template)
                for k, v in resolved.items():
                    query = query.replace(f"{{{k}}}", str(v))
                lines.append(
                    f"- **{role}**: `lib_recommend_part(category={query!r})`"
                )
        else:
            lines.append(
                "- Use lib_search_components() or lib_recommend_part() for each symbol."
            )

        lines += [
            "",
            "## Step 4: Footprint Assignment",
            (
                "For each symbol: `lib_bind_part_to_symbol(sym_ref, lcsc_code, "
                "auto_assign_footprint=True)`"
            ),
            "",
            "## Placement Hints",
        ]
        for hint in hints:
            lines.append(f"- {hint}")

        return "\n".join(lines)

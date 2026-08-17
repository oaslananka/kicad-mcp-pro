"""Schematic tools with parser-based reads and transactional writes."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import threading
import time
import uuid
from collections.abc import Callable, Iterable
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Literal, Protocol, TextIO, TypedDict, cast

import structlog
from mcp.server.fastmcp import FastMCP

from ..config import get_config
from ..connection import KiCadConnectionError, get_kicad
from ..discovery import is_numbered_duplicate_kicad_file
from ..errors import SchematicWriteUnsafeError
from ..models.schematic import (
    STANDARD_SYMBOL_FIELDS,
    AddLabelInput,
    AddSymbolInput,
    AddWireInput,
    PowerSymbolInput,
    UpdatePropertiesInput,
)
from ..models.visual_qa import run_visual_qa as _run_visual_qa
from ..path_safety import resolve_under
from ..schematic.back_annotation import SchematicBackAnnotationService
from ..schematic.basic_authoring import SchematicBasicAuthoringService
from ..schematic.circuit_compilation import (
    PreparedCircuitInputs,
    SchematicCircuitCompilationService,
)
from ..schematic.connectivity_authoring import (
    BoundingBoxLike,
    SchematicConnectivityAuthoringService,
    SchematicTargetLike,
)
from ..schematic.destructive_edit import SchematicDestructiveEditService
from ..schematic.document_settings import SchematicDocumentSettingsService
from ..schematic.hierarchy_authoring import (
    ChildSchematic,
    RootSchematic,
    SchematicHierarchyAuthoringService,
)
from ..schematic.inspection import SchematicInspectionService
from ..schematic.layout_automation import (
    FunctionalDesignIntentLike,
    SchematicLayoutAutomationService,
    SchematicLike,
)
from ..schematic.layout_inspection import SchematicLayoutInspectionService
from ..schematic.lifecycle_authoring import SchematicLifecycleAuthoringService
from ..schematic.rendering import SchematicRenderingService
from ..schematic.semantic_ir import (
    CircuitLike,
    FindingLike,
    SchematicSemanticIRService,
)
from ..schematic.symbol_mutation import SchematicSymbolMutationService
from ..schematic.template_catalog import SchematicTemplateCatalogService
from ..schematic.template_instantiation import SchematicTemplateInstantiationService
from ..schematic.topology import SchematicTopologyService
from ..utils.cache import clear_ttl_cache
from ..utils.field_placer import FieldSpec, autoplace_fields
from ..utils.geometry import Box as GeoBox
from ..utils.geometry import body_box_from_pins, text_extent
from ..utils.schematic_roundtrip import dropped_nodes
from ..utils.schematic_router import RouterBBox, SchematicRouter
from ..utils.sexpr import (
    _escape_sexpr_string,
    _extract_block,
    _sexpr_string,
    _unescape_sexpr_string,
)
from . import (
    schematic_back_annotation,
    schematic_basic_authoring,
    schematic_circuit_compilation,
    schematic_connectivity_authoring,
    schematic_destructive_edit,
    schematic_document_settings,
    schematic_hierarchy_authoring,
    schematic_inspection,
    schematic_layout_automation,
    schematic_layout_inspection,
    schematic_lifecycle_authoring,
    schematic_rendering,
    schematic_semantic_ir,
    schematic_symbol_mutation,
    schematic_template_catalog,
    schematic_template_instantiation,
    schematic_topology,
)
from .schematic_constants import (
    _SCHEMATIC_STATE_DIRNAME,
    _SHEET_MARGIN_MM,
    AUTO_LAYOUT_COLUMN_SPACING_MM,
    AUTO_LAYOUT_COLUMNS,
    AUTO_LAYOUT_ORIGIN_X_MM,
    AUTO_LAYOUT_ORIGIN_Y_MM,
    AUTO_LAYOUT_ROW_SPACING_MM,
    DEFAULT_SHEET_HEIGHT_MM,
    DEFAULT_SHEET_WIDTH_MM,
    NETLIST_LABEL_OFFSET_MM,
    NETLIST_LAYOUT_COLUMN_SPACING_MM,
    NETLIST_LAYOUT_ROW_SPACING_MM,
    NETLIST_POWER_OFFSET_MM,
    ORIGIN_PIN_POWER_SYMBOL_NAMES,
    PAPER_SIZES_MM,
    POWER_NET_NAMES,
    SCHEMATIC_GRID_MM,
    SNAP_TOLERANCE_MM,
)

# Re-export the public tool-name list (consumed by the router and tests) from the
# extracted constants module without tripping the unused-import lint.
from .schematic_constants import (
    SCHEMATIC_PUBLIC_TOOL_NAMES as SCHEMATIC_PUBLIC_TOOL_NAMES,
)

_SCHEMATIC_WRITE_LOCK = threading.RLock()
logger = structlog.get_logger(__name__)

SchematicCapabilityStatus = Literal["native", "wrapper_needed"]


class SchematicCapabilityEntry(TypedDict):
    kicad_sch_api_support: SchematicCapabilityStatus
    verified_surface: list[str]
    notes: str


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
    "sch_live_preview": {
        "kicad_sch_api_support": "wrapper_needed",
        "verified_surface": [
            "kicad-cli sch export svg",
            "KiCad IPC reload helper outside kicad-sch-api",
        ],
        "notes": (
            "Live preview is an opt-in polling wrapper over file signatures, safe PNG "
            "rendering, and optional KiCad reload; it is intentionally not a blind "
            "GUI hot-reload."
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
            "Detailed sheet metadata is available directly from SheetManager.get_sheet_by_name()."
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
    "sch_autoplace_fields": {
        "kicad_sch_api_support": "wrapper_needed",
        "verified_surface": ["ComponentCollection.get"],
        "notes": (
            "Reference/Value field auto-placement is a deterministic S-expression "
            "wrapper; kicad-sch-api does not expose KiCad's autoplace_fields."
        ),
    },
    "sch_fix_readability": {
        "kicad_sch_api_support": "wrapper_needed",
        "verified_surface": ["ComponentCollection.get"],
        "notes": (
            "Closed-loop readability fixer orchestrating headless visual-QA, field "
            "auto-placement, and sheet resizing; no direct kicad-sch-api surface."
        ),
    },
}


class _SchematicBackendAdapter(Protocol):
    name: str
    capability_matrix: dict[str, SchematicCapabilityEntry]

    def parse_schematic_file(self, sch_file: Path) -> dict[str, Any]:
        raise NotImplementedError

    def transactional_write(self, mutator: Callable[[str], str]) -> str:
        raise NotImplementedError

    def update_symbol_property(self, reference: str, field: str, value: str) -> str:
        raise NotImplementedError

    def reload_schematic(self) -> str:
        raise NotImplementedError


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

    def set_property(self, name: str, value: str) -> object:
        raise NotImplementedError

    def move(self, x: float, y: float) -> object:
        raise NotImplementedError


class _ComponentCollectionLike(Protocol):
    def all(self) -> Iterable[_PlacedComponentLike]:
        raise NotImplementedError

    def get(self, reference: str) -> _PlacedComponentLike | None:
        raise NotImplementedError


class _LabelLike(Protocol):
    text: str
    position: _PointLike
    rotation: float


class _LabelCollectionLike(Protocol):
    def all(self) -> Iterable[_LabelLike]:
        raise NotImplementedError


class _WireLike(Protocol):
    start: _PointLike
    end: _PointLike


class _WireCollectionLike(Protocol):
    def all(self) -> Iterable[_WireLike]:
        raise NotImplementedError


class _SheetManagerLike(Protocol):
    def get_sheet_hierarchy(self) -> dict[str, Any]:
        raise NotImplementedError

    def get_sheet_by_name(self, name: str) -> dict[str, Any] | None:
        raise NotImplementedError


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
    ) -> str:
        raise NotImplementedError

    def save(self, file_path: Path | str | None = None, preserve_format: bool = True) -> object:
        raise NotImplementedError


def _load_kicad_schematic(sch_file: Path) -> _LoadedSchematicLike:
    from kicad_sch_api import load_schematic

    return cast(_LoadedSchematicLike, load_schematic(str(sch_file)))


def _load_hierarchy_schematic(sch_file: Path) -> RootSchematic:
    return cast(RootSchematic, _load_kicad_schematic(sch_file))


def _resolve_create_schematic() -> Callable[[str], ChildSchematic]:
    from kicad_sch_api import create_schematic

    return cast(Callable[[str], ChildSchematic], create_schematic)


def _component_unit(component: _PlacedComponentLike) -> int:
    return int(getattr(getattr(component, "_data", None), "unit", 1) or 1)


def _component_to_symbol_dict(component: _PlacedComponentLike) -> dict[str, Any]:
    return {
        "lib_id": str(component.lib_id),
        "reference": str(component.reference),
        "value": str(component.value),
        "footprint": str(component.footprint or ""),
        # The kicad-sch-api SchematicSymbol models in_bom/on_board but not the
        # native dnp flag, so dnp is recovered from the file by callers that
        # need it (see native_population_flags).
        "dnp": bool(getattr(getattr(component, "_data", None), "dnp", False)),
        "in_bom": bool(getattr(component, "in_bom", True)),
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
        _ = self
        return _update_symbol_property_text_fallback(reference, field, value)

    def reload_schematic(self) -> str:
        return _reload_schematic_via_ipc()


_SCHEMATIC_BACKENDS: dict[str, _SchematicBackendAdapter] = {
    "kicad_sch_api": cast(_SchematicBackendAdapter, _KicadSchApiBackend()),
}
_DEFAULT_SCHEMATIC_BACKEND = "kicad_sch_api"


def get_schematic_backend() -> _SchematicBackendAdapter:
    """Return the currently active schematic backend adapter."""
    return _SCHEMATIC_BACKENDS[_DEFAULT_SCHEMATIC_BACKEND]


@dataclass(frozen=True)
class _SchematicTarget:
    path: Path
    is_root: bool
    description: str


def _format_target_detail(target: _SchematicTarget) -> str:
    kind = "root" if target.is_root else "child"
    return f"Target schematic ({kind}): {target.path}"


def _available_sheet_names(root_schematic: Path) -> list[str]:
    return [name for name, _ in _iter_child_sheet_paths(root_schematic)]


def _resolve_schematic_target(
    sheet: str | None = None,
    sheet_file: str | None = None,
) -> _SchematicTarget:
    """Resolve an optional child-sheet target for file-backed tools."""
    if sheet and sheet_file:
        raise ValueError("Use only one of sheet or sheet_file.")

    root = _get_schematic_file().resolve()
    cfg = get_config()
    project_root = (cfg.project_dir or root.parent).resolve()

    if sheet_file:
        target = resolve_under(project_root, sheet_file).resolve()
        if target.suffix != ".kicad_sch":
            raise ValueError("sheet_file must point to a .kicad_sch file.")
        if not target.exists():
            raise ValueError(f"Target schematic file does not exist: {target}")
        return _SchematicTarget(
            path=target,
            is_root=target == root,
            description="root" if target == root else "child",
        )

    if sheet:
        discovered = _iter_child_sheet_paths(root)
        matches = [
            (name, path.resolve())
            for name, path in discovered
            if name == sheet or name.rsplit("/", 1)[-1] == sheet
        ]
        if not matches:
            available = ", ".join(_available_sheet_names(root)) or "(none)"
            raise ValueError(f"Sheet '{sheet}' was not found. Available sheets: {available}")
        if len(matches) > 1:
            available = ", ".join(name for name, _ in matches)
            raise ValueError(f"Sheet '{sheet}' is ambiguous. Matching sheets: {available}")
        name, target = matches[0]
        if not target.exists():
            raise ValueError(f"Sheet '{name}' points to missing file: {target}")
        resolve_under(project_root, target)
        return _SchematicTarget(path=target, is_root=target == root, description=name)

    return _SchematicTarget(path=root, is_root=True, description="root")


def new_uuid() -> str:
    """Create a KiCad UUID string."""
    return str(uuid.uuid4())


_STRING_PATTERN = r'"((?:\\.|[^"\\])*)"'
_FLOAT_PATTERN = r"-?\d+(?:\.\d+)?"

# Property used to record why a component is marked Do Not Populate.
DNP_REASON_PROPERTY = "DNP Reason"


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
_SYMBOL_HALF_W_MM = 10.16  # ~4 pins wide  (2 × 2.54 × 2)
_SYMBOL_HALF_H_MM = 7.62  # ~3 pins tall


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
    "connector": (0, 0),  # Left — connectors, headers
    "mcu": (3, 0),  # Centre-left — main processor
    "ui": (6, 0),  # Right — LED, buzzer, button, switch
    "power_ic": (0, 3),  # Left-mid — LDO, buck, PMU
    "sensor": (3, 3),  # Centre-mid — sensors
    "ic": (3, 3),  # Generic IC — shares sensor zone
    "protection": (6, 3),  # Right-mid — ESD, TVS, fuse, diode
    "power_pass": (0, 5),  # Left-lower — bulk caps, ferrite, input
    "passive_cap": (2, 5),  # Lower-centre-left — decoupling caps
    "passive_res": (4, 5),  # Lower-centre — resistors
    "transistor": (6, 5),  # Right-lower — MOSFET, BJT
    "filter": (6, 6),  # Right-bottom — ferrite, LC filter
    "testpoint": (0, 7),  # Bottom-left — test points
    "misc": (5, 7),  # Bottom-right — anything else
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
            k in lib_up for k in ("ESP32", "STM32", "ATMEGA", "NRF5", "RP2", "PIC", "RF_MODULE")
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


# Standard ISO-A landscape ladder, smallest first. Auto-layout climbs this ladder
# when a circuit does not fit the current sheet so generated symbols never spill
# past the sheet boundary (the off-sheet defect `sch_visual_qa` reports).
_PAPER_LADDER: tuple[str, ...] = ("A4", "A3", "A2", "A1", "A0")


def _paper_capacity_rows(
    paper: str,
    *,
    cell_w: float = AUTO_LAYOUT_COLUMN_SPACING_MM,
    cell_h: float = AUTO_LAYOUT_ROW_SPACING_MM,
) -> tuple[int, int]:
    """Return ``(usable_cols, usable_rows)`` for a paper at a given cell pitch."""
    return _sheet_usable_cols(paper, cell_w), _sheet_usable_rows(paper, cell_h)


def _ladder_cap_index(max_paper: str | None) -> int:
    """Return the ladder index the auto-layout climb may not exceed.

    ``max_paper=None`` means "no cap" (the historical unbounded behaviour) and
    yields the largest ladder entry. Any other value must be a known ladder
    entry; validation is the caller's responsibility (see
    ``_prepare_build_circuit_inputs``).
    """
    if max_paper is None:
        return len(_PAPER_LADDER) - 1
    try:
        return _PAPER_LADDER.index(max_paper)
    except ValueError as exc:
        raise ValueError(
            f"Invalid max_paper {max_paper!r}. Expected one of {', '.join(_PAPER_LADDER)} or None."
        ) from exc


def select_paper_for_capacity(
    required_rows: int,
    *,
    start_paper: str = "A4",
    max_paper: str | None = None,
    cell_w: float = AUTO_LAYOUT_COLUMN_SPACING_MM,
    cell_h: float = AUTO_LAYOUT_ROW_SPACING_MM,
) -> str:
    """Return the smallest standard paper (>= ``start_paper``) holding ``required_rows``.

    Never downsizes below ``start_paper`` so an explicit large sheet is preserved.
    The climb never grows the sheet beyond ``max_paper``: if ``required_rows`` does
    not fit at the cap, the cap is returned and callers place multi-column /
    multi-row within it rather than climbing higher. ``max_paper=None`` restores
    the historical unbounded climb (largest ladder entry is the effective cap).
    """
    start = start_paper if start_paper in _PAPER_LADDER else "A4"
    start_index = _PAPER_LADDER.index(start)
    cap_index = max(start_index, _ladder_cap_index(max_paper))
    for paper in _PAPER_LADDER[start_index : cap_index + 1]:
        _, usable_rows = _paper_capacity_rows(paper, cell_w=cell_w, cell_h=cell_h)
        if usable_rows >= required_rows:
            return paper
    return _PAPER_LADDER[cap_index]


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


def _read_sheet_paper_declaration(sch_file: Path) -> str:
    """Read the full paper declaration from a schematic, including User dimensions."""
    try:
        text = sch_file.read_text(encoding="utf-8", errors="replace")
        match = re.search(r'\(paper\s+"[^"]+"(?:\s+[\d.]+\s+[\d.]+)?\)', text)
        if match:
            return match.group(0)
    except Exception as exc:
        logger.debug("sheet_paper_declaration_parse_failed", error=str(exc))
    return '(paper "A4")'


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
        start_col = int(math.floor((x_min - _SYMBOL_HALF_W_MM - AUTO_LAYOUT_ORIGIN_X_MM) / cell_w))
        end_col = int(math.ceil((x_max + _SYMBOL_HALF_W_MM - AUTO_LAYOUT_ORIGIN_X_MM) / cell_w))
        start_row = int(math.floor((y_min - _SYMBOL_HALF_H_MM - AUTO_LAYOUT_ORIGIN_Y_MM) / cell_h))
        end_row = int(math.ceil((y_max + _SYMBOL_HALF_H_MM - AUTO_LAYOUT_ORIGIN_Y_MM) / cell_h))
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


_NET_SCOPE_TO_LABEL_KIND = {
    "local": "label",
    "global": "global_label",
    "hierarchical": "hierarchical_label",
}


def _net_label_kind(net: dict[str, Any]) -> str | None:
    """Map an optional per-net ``scope`` to a label ``kind`` for terminal labels.

    Returns ``None`` when ``scope`` is omitted so callers keep the historical
    default (global labels).  ``local`` → plain label, ``global`` → global label,
    ``hierarchical`` → hierarchical label.  Any other value raises ``ValueError``.
    """
    scope = net.get("scope")
    if scope is None:
        return None
    try:
        return _NET_SCOPE_TO_LABEL_KIND[scope]
    except (KeyError, TypeError):
        allowed = ", ".join(sorted(_NET_SCOPE_TO_LABEL_KIND))
        raise ValueError(f"Invalid net scope {scope!r}; expected one of: {allowed}.") from None


def _is_power_net(name: str) -> bool:
    upper_name = name.upper()
    if upper_name in POWER_NET_NAMES or upper_name.startswith(("+", "-")):
        return True
    if re.match(r"^\d+(?:V\d*)?(?:_[A-Z0-9]+)?$", upper_name):
        return "V" in upper_name
    if upper_name.startswith(("V", "VBUS", "VBAT", "VPOE")) and any(
        char.isdigit() for char in upper_name
    ):
        return True
    return False


def _has_power_symbol_definition(name: str) -> bool:
    return load_lib_symbol("power", name) is not None


def _should_place_power_terminal_symbol(name: str) -> bool:
    return _is_power_net(name) and _has_power_symbol_definition(name)


def _is_origin_pin_power_symbol(symbol_name: str, value: str) -> bool:
    """Return whether a no-pin power symbol is conventionally anchored at origin."""
    candidates = {symbol_name, value}
    for candidate in candidates:
        normalized = candidate.strip()
        if not normalized:
            continue
        upper = normalized.upper()
        if _is_power_net(normalized) or upper in {
            name.upper() for name in ORIGIN_PIN_POWER_SYMBOL_NAMES
        }:
            return True
        if upper.startswith(("#PWR", "PWR_FLAG", "GNDPWR", "GNDREF")):
            return True
    return False


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


# Room reserved around a symbol body for its terminal stubs + global-label text,
# so a connected neighbour (and its labels) cannot land on top of this symbol.
_NETLIST_LABEL_MARGIN_W_MM = 22.0
_NETLIST_LABEL_MARGIN_H_MM = 12.0


def _symbol_local_extent(symbol: dict[str, Any]) -> tuple[float, float, float, float] | None:
    """Return ``(min_dx, min_dy, width, height)`` of a symbol's pins about its origin.

    Offsets are relative to the placement point, so a caller can align the body
    inside a reserved grid block. ``None`` when the symbol's pins cannot be read.
    """
    library = str(symbol.get("library", "") or "")
    name = str(symbol.get("symbol_name", "") or "")
    if not library or not name:
        return None
    try:
        pins = get_pin_positions(
            library,
            name,
            0.0,
            0.0,
            int(symbol.get("rotation", 0) or 0),
            int(symbol.get("unit", 1) or 1),
        )
    except (FileNotFoundError, OSError, ValueError):
        return None
    if not pins:
        return None
    xs = [p[0] for p in pins.values()]
    ys = [p[1] for p in pins.values()]
    return (min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))


def _symbol_footprint_cells(
    extent: tuple[float, float, float, float] | None, cell_w: float, cell_h: float
) -> tuple[int, int]:
    """Cells a symbol (body + label margin) needs, at least 1×1."""
    if extent is None:
        return (1, 1)
    _, _, width, height = extent
    cols = max(1, math.ceil((width + _NETLIST_LABEL_MARGIN_W_MM) / cell_w))
    rows = max(1, math.ceil((height + _NETLIST_LABEL_MARGIN_H_MM) / cell_h))
    return (cols, rows)


def _next_free_block(
    occupied: set[tuple[int, int]],
    fcols: int,
    frows: int,
    *,
    cell_w: float,
    cell_h: float,
    paper: str,
) -> tuple[int, int]:
    """Reserve a free ``fcols×frows`` block of grid cells; return its ``(col, row)``.

    Row-major first fit. Columns are bounded by the paper so a wide block never
    overflows the sheet width (the block itself may exceed it for very wide parts,
    in which case it starts at column 0).
    """
    max_cols = max(_sheet_usable_cols(paper, cell_w), fcols)
    col, row = 0, 0
    while True:
        if col + fcols <= max_cols:
            block = [(col + dc, row + dr) for dc in range(fcols) for dr in range(frows)]
            if not any(cell in occupied for cell in block):
                occupied.update(block)
                return col, row
        col += 1
        if col + fcols > max_cols:
            col, row = 0, row + 1


def _apply_netlist_auto_layout(
    symbols: list[dict[str, Any]],
    power_symbols: list[dict[str, Any]],
    labels: list[dict[str, Any]],
    nets: list[dict[str, Any]],
    *,
    paper: str = "A4",
    max_paper: str | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], str]:
    laid_out_symbols = [dict(item) for item in symbols]
    laid_out_powers = [dict(item) for item in power_symbols]
    laid_out_labels = [dict(item) for item in labels]
    refs = [str(symbol["reference"]) for symbol in laid_out_symbols if symbol.get("reference")]
    ordered_refs = _order_refs_by_connectivity(refs, nets)

    cell_w = NETLIST_LAYOUT_COLUMN_SPACING_MM
    cell_h = NETLIST_LAYOUT_ROW_SPACING_MM
    sym_by_ref = {str(s.get("reference", "")): s for s in laid_out_symbols if s.get("reference")}

    # Size-aware: each symbol reserves a grid block sized to its real pin extent
    # plus a margin for terminal stubs/labels, so a large multi-pin part (and its
    # label fan-out) cannot land on top of a neighbour. Footprints are computed
    # once and reused for sheet sizing and placement.
    footprints: dict[str, tuple[int, int]] = {}
    offsets: dict[str, tuple[float, float, float, float] | None] = {}
    for reference, symbol in sym_by_ref.items():
        extent = _symbol_local_extent(symbol)
        offsets[reference] = extent
        footprints[reference] = _symbol_footprint_cells(extent, cell_w, cell_h)

    start_paper = paper if paper in _PAPER_LADDER else "A4"
    usable_cols = max(1, _sheet_usable_cols(start_paper, cell_w))
    total_cells = sum(fc * fr for fc, fr in footprints.values()) or 1
    required_rows = math.ceil(total_cells / usable_cols) + 2
    chosen_paper = select_paper_for_capacity(
        required_rows,
        start_paper=start_paper,
        max_paper=max_paper,
        cell_w=cell_w,
        cell_h=cell_h,
    )

    # Use occupancy grid to avoid symbol collisions in netlist layout too.
    netlist_occupied: set[tuple[int, int]] = set()
    for symbol in laid_out_symbols:
        if _has_point(symbol):
            sx = _coord_value(symbol, "x") or 0.0
            sy = _coord_value(symbol, "y") or 0.0
            col = int(round((sx - AUTO_LAYOUT_ORIGIN_X_MM) / cell_w))
            row = int(round((sy - AUTO_LAYOUT_ORIGIN_Y_MM) / cell_h))
            netlist_occupied.add((col, row))

    generated_positions: dict[str, tuple[float, float]] = {}
    for reference in ordered_refs:
        fcols, frows = footprints.get(reference, (1, 1))
        col, row = _next_free_block(
            netlist_occupied, fcols, frows, cell_w=cell_w, cell_h=cell_h, paper=chosen_paper
        )
        cell_x = AUTO_LAYOUT_ORIGIN_X_MM + col * cell_w
        cell_y = AUTO_LAYOUT_ORIGIN_Y_MM + row * cell_h
        extent = offsets.get(reference)
        if extent is not None:
            min_dx, min_dy, _, _ = extent
            # Seat the body inside the block with a half-margin gutter for labels.
            raw_x = cell_x - min_dx + _NETLIST_LABEL_MARGIN_W_MM / 2.0
            raw_y = cell_y - min_dy + _NETLIST_LABEL_MARGIN_H_MM / 2.0
            generated_positions[reference] = _snap_point(raw_x, raw_y, True)
        else:
            generated_positions[reference] = (cell_x, cell_y)

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
                    paper=chosen_paper,
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

    return laid_out_symbols, laid_out_powers, laid_out_labels, chosen_paper


def _basic_layout_bottom_row(n_symbols: int, n_gnd: int, n_labels: int, cols: int) -> int:
    """Return the 0-based index of the lowest row the basic layout will fill.

    Symbols fill rows ``0..symbol_rows-1`` at ``cols`` per row, GND power symbols
    sit on the next row band, and labels below those. Used to size the sheet so
    nothing is placed past the bottom margin.
    """
    cols = max(1, cols)
    symbol_rows = max(1, math.ceil(max(n_symbols, 1) / cols))
    bottom = symbol_rows - 1
    gnd_row = symbol_rows
    if n_gnd:
        bottom = max(bottom, gnd_row + math.ceil(n_gnd / cols) - 1)
    if n_labels:
        label_row = gnd_row + 1
        bottom = max(bottom, label_row + math.ceil(n_labels / cols) - 1)
    return bottom


def _apply_basic_auto_layout(
    symbols: list[dict[str, Any]],
    power_symbols: list[dict[str, Any]],
    labels: list[dict[str, Any]],
    *,
    paper: str = "A4",
    max_paper: str | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], str]:
    laid_out_symbols = [dict(item) for item in symbols]
    laid_out_powers = [dict(item) for item in power_symbols]
    laid_out_labels = [dict(item) for item in labels]

    # Grow the sheet up the paper ladder while the layout fits the candidate.
    # The climb is capped at ``max_paper``; once the cap is reached, placement
    # continues using that paper's column grid instead of selecting a larger
    # sheet. Extremely dense inputs can still exceed the capped page height, so
    # callers must rely on visual/layout validation rather than the cap alone.
    n_gnd = sum(1 for p in laid_out_powers if str(p.get("name", "")).upper().startswith("GND"))
    start_paper = paper if paper in _PAPER_LADDER else "A4"
    start_index = _PAPER_LADDER.index(start_paper)
    cap_index = max(start_index, _ladder_cap_index(max_paper))
    chosen_paper = start_paper
    for candidate in _PAPER_LADDER[start_index : cap_index + 1]:
        cols = _sheet_usable_cols(candidate)
        bottom = _basic_layout_bottom_row(len(laid_out_symbols), n_gnd, len(laid_out_labels), cols)
        # +1 for the GND/label bands' own rows already counted; the positive-rail
        # band sits at row -1 which the origin margin always accommodates.
        if bottom < _sheet_usable_rows(candidate):
            chosen_paper = candidate
            break
        chosen_paper = candidate
    max_cols = _sheet_usable_cols(chosen_paper)

    # Use occupancy grid so every symbol gets a unique, non-overlapping slot.
    occupied: set[tuple[int, int]] = set()
    for symbol in laid_out_symbols:
        x, y = _next_free_cell(occupied, max_cols=max_cols)
        symbol["x_mm"] = x
        symbol["y_mm"] = y
        symbol.setdefault("snap_to_grid", True)

    symbol_rows = max(1, math.ceil(max(len(laid_out_symbols), 1) / max_cols))
    gnd_row = symbol_rows
    positive_row = -1  # above origin row

    pwr_occupied_gnd: set[tuple[int, int]] = set()
    pwr_occupied_pos: set[tuple[int, int]] = set()

    for power_symbol in laid_out_powers:
        name = str(power_symbol.get("name", "")).upper()
        if name.startswith("GND"):
            x, y = _next_free_cell(pwr_occupied_gnd, start_row=gnd_row, max_cols=max_cols)
        else:
            x, y = _next_free_cell(pwr_occupied_pos, start_row=positive_row, max_cols=max_cols)
        power_symbol["x_mm"] = x
        power_symbol["y_mm"] = y
        power_symbol.setdefault("snap_to_grid", True)

    label_row = gnd_row + 1
    lbl_occupied: set[tuple[int, int]] = set()
    for label in laid_out_labels:
        x, y = _next_free_cell(lbl_occupied, start_row=label_row, max_cols=max_cols)
        label["x_mm"] = x
        label["y_mm"] = y
        label.setdefault("snap_to_grid", True)

    return laid_out_symbols, laid_out_powers, laid_out_labels, chosen_paper


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
    # The root sheet UUID is the first ``(uuid ...)`` after ``(kicad_sch`` — but
    # ``(version ...)`` / ``(generator ...)`` sit between them, so a ``[^(]*`` gap
    # never matches a real file. Use a non-greedy DOTALL span to reach the first
    # UUID (the root), not a later symbol/wire UUID.
    match = re.search(r'\(kicad_sch\b.*?\(uuid\s+"([^"]+)"', content, re.DOTALL)
    return match.group(1) if match else ""


def _find_title_block(content: str) -> tuple[int, str] | None:
    for match in re.finditer(r"\(title_block\b", content):
        block, length = _extract_block(content, match.start())
        if block:
            return match.start(), block[:length]
    return None


def _replace_or_insert_title_line(block: str, pattern: re.Pattern[str], line: str) -> str:
    if pattern.search(block):
        return pattern.sub(line, block, count=1)
    insert_at = block.rfind("\n")
    if insert_at == -1:
        return f"(title_block\n\t\t{line}\n\t)"
    return f"{block[:insert_at]}\n\t\t{line}{block[insert_at:]}"


def _apply_title_block_updates(content: str, updates: dict[str, str]) -> str:
    field_patterns = {
        "title": re.compile(rf"\(title\s+{_STRING_PATTERN}\)"),
        "date": re.compile(rf"\(date\s+{_STRING_PATTERN}\)"),
        "rev": re.compile(rf"\(rev\s+{_STRING_PATTERN}\)"),
        "company": re.compile(rf"\(company\s+{_STRING_PATTERN}\)"),
    }
    comment_patterns = {
        f"comment{index}": re.compile(rf"\(comment\s+{index}\s+{_STRING_PATTERN}\)")
        for index in range(1, 5)
    }

    found = _find_title_block(content)
    if found is None:
        lines = ["\t(title_block"]
        for key in ("title", "date", "rev", "company"):
            if key in updates:
                lines.append(f"\t\t({key} {_sexpr_string(updates[key])})")
        for index in range(1, 5):
            key = f"comment{index}"
            if key in updates:
                lines.append(f"\t\t(comment {index} {_sexpr_string(updates[key])})")
        lines.append("\t)")
        block = "\n".join(lines)
        paper_match = re.search(r"(\n\s*\(paper\b[^\n]*\)\n)", content)
        if paper_match:
            return content[: paper_match.end()] + block + "\n" + content[paper_match.end() :]
        return _append_before_sheet_instances(content, block)

    start, block = found
    updated = block
    for key, pattern in field_patterns.items():
        if key in updates:
            updated = _replace_or_insert_title_line(
                updated,
                pattern,
                f"({key} {_sexpr_string(updates[key])})",
            )
    for index in range(1, 5):
        key = f"comment{index}"
        if key in updates:
            updated = _replace_or_insert_title_line(
                updated,
                comment_patterns[key],
                f"(comment {index} {_sexpr_string(updates[key])})",
            )
    return f"{content[:start]}{updated}{content[start + len(block) :]}"


def _safe_render_output_path(raw_name: str | None, *, default_name: str) -> Path:
    from .export_support import _ensure_output_dir

    name = (raw_name or default_name).strip()
    if not name:
        raise ValueError("output_file cannot be empty.")
    if "/" in name or "\\" in name or Path(name).name != name:
        raise ValueError("output_file must be a file name relative to the schematic render dir.")
    if Path(name).suffix.lower() not in {"", ".png"}:
        raise ValueError("output_file must use the .png extension.")
    if not name.lower().endswith(".png"):
        name = f"{name}.png"
    return _ensure_output_dir("schematic-renders") / name


def _schematic_has_renderable_content(data: dict[str, Any]) -> bool:
    for key in ("symbols", "power_symbols", "wires", "labels", "buses"):
        if data.get(key):
            return True
    return False


def _schematic_live_preview_state_filename(sch_file: Path, include_child_sheets: bool) -> str:
    suffix = "tree" if include_child_sheets else "sheet"
    key = hashlib.sha256(f"{sch_file.resolve()}::{suffix}".encode()).hexdigest()[:16]
    return f"live-preview-{suffix}-{key}.json"


def _schematic_live_preview_files(root: Path, include_child_sheets: bool) -> list[Path]:
    files = [root.resolve()]
    if include_child_sheets:
        for _name, child in _iter_child_sheet_paths(root):
            resolved = child.resolve()
            if resolved not in files:
                files.append(resolved)
    return files


def _schematic_live_preview_signature(paths: list[Path]) -> dict[str, Any]:
    files: list[dict[str, Any]] = []
    for path in paths:
        item: dict[str, Any] = {"path": str(path), "exists": path.exists()}
        if path.exists():
            stat = path.stat()
            content = path.read_bytes()
            item.update(
                {
                    "size": stat.st_size,
                    "mtime_ns": stat.st_mtime_ns,
                    "sha256": hashlib.sha256(content).hexdigest(),
                }
            )
        files.append(item)
    return {"files": files}


def _schematic_live_preview_changed_files(
    before: dict[str, Any] | None,
    after: dict[str, Any],
) -> list[str]:
    before_files = {
        str(item.get("path")): item
        for item in cast(list[dict[str, Any]], (before or {}).get("files", []))
    }
    changed: list[str] = []
    for item in cast(list[dict[str, Any]], after.get("files", [])):
        path = str(item.get("path"))
        if before_files.get(path) != item:
            changed.append(path)
    for path in before_files:
        if path not in {
            str(item.get("path")) for item in cast(list[dict[str, Any]], after.get("files", []))
        }:
            changed.append(path)
    return sorted(set(changed))


def _schematic_live_preview_render_path(
    *,
    target_path: Path,
    watched_files: list[Path],
    changed_files: list[str],
) -> Path:
    """Choose the schematic sheet to render for a live-preview refresh."""
    changed = {str(Path(path).resolve()) for path in changed_files}
    for path in watched_files:
        resolved = path.resolve()
        if str(resolved) in changed and resolved.exists():
            try:
                if _schematic_has_renderable_content(parse_schematic_file(resolved)):
                    return resolved
            except Exception as exc:
                logger.debug(
                    "schematic_live_preview_render_candidate_failed",
                    schematic_file=str(resolved),
                    error=str(exc),
                )
                continue
    return target_path.resolve()


def _schematic_live_preview_payload(
    *,
    status: str,
    target: _SchematicTarget,
    files: list[Path],
    signature: dict[str, Any],
    changed_files: list[str] | None = None,
    message: str | None = None,
    reload_result: str | None = None,
    render_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "status": status,
        "target": target.description,
        "target_path": str(target.path),
        "watch_files": [str(path) for path in files],
        "signature": signature,
        "changed_files": changed_files or [],
    }
    if message:
        payload["message"] = message
    if reload_result:
        payload["reload_result"] = reload_result
    if render_metadata:
        payload["render"] = render_metadata
    contract = __import__(
        "kicad_mcp.models.live_preview", fromlist=["LivePreviewPayload"]
    ).LivePreviewPayload.from_legacy_payload(payload)  # noqa: E501
    normalized = contract.model_dump(mode="json", exclude_none=True)  # noqa: E501
    payload.update(normalized)
    payload["watch_files"] = list(contract.watched_files)
    payload["changed_files"] = list(contract.changed_files)
    return payload


def _schematic_live_preview_state_read(filename: str) -> dict[str, Any] | None:
    path = _schematic_state_path(filename)
    if not path.exists():
        return None
    try:
        return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError):
        return None


def _schematic_live_preview_state_write(filename: str, state: dict[str, Any]) -> None:
    path = _schematic_state_path(filename)
    path.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")


def _export_schematic_svg_for_render(
    sch_file: Path,
    out_dir: Path,
    *,
    include_title_block: bool,
) -> tuple[int, str, str]:
    from .export_support import _run_cli_variants

    common_args = ["--no-background-color"]
    if not include_title_block:
        common_args.append("--exclude-drawing-sheet")
    return _run_cli_variants(
        [
            ["sch", "export", "svg", *common_args, "--output", str(out_dir), str(sch_file)],
            [
                "sch",
                "export",
                "svg",
                *common_args,
                "--input",
                str(sch_file),
                "--output",
                str(out_dir),
            ],
        ]
    )


def _latest_svg_file(out_dir: Path, known_files: set[Path]) -> Path | None:
    candidates = sorted(out_dir.glob("*.svg"), key=lambda path: path.stat().st_mtime)
    new_files = [path for path in candidates if path not in known_files]
    if new_files:
        return new_files[-1]
    return candidates[-1] if candidates else None


def _render_svg_to_png(
    svg_file: Path,
    output_file: Path,
    *,
    dpi: int,
    crop_to_content: bool,
) -> dict[str, object]:
    try:
        import cairosvg  # type: ignore[import-not-found, import-untyped, unused-ignore]
        from PIL import Image
    except ImportError as exc:
        raise RuntimeError(
            "PNG rendering requires CairoSVG and Pillow. Install the project dev extras "
            "or run uv sync --all-extras --frozen."
        ) from exc

    raw_file = (
        output_file.with_name(f"{output_file.stem}.full.png") if crop_to_content else output_file
    )
    cairosvg.svg2png(url=str(svg_file), write_to=str(raw_file), dpi=dpi)
    with Image.open(raw_file) as image:
        rgba = image.convert("RGBA")
        bbox = rgba.getbbox()
        if crop_to_content and bbox is not None:
            margin = max(4, int(dpi * 0.04))
            left = max(0, bbox[0] - margin)
            top = max(0, bbox[1] - margin)
            right = min(rgba.width, bbox[2] + margin)
            bottom = min(rgba.height, bbox[3] + margin)
            rgba.crop((left, top, right, bottom)).save(output_file)
            cropped = True
        else:
            rgba.save(output_file)
            cropped = False
    if raw_file != output_file and raw_file.exists():
        raw_file.unlink()
    with Image.open(output_file) as rendered:
        return {
            "width_px": rendered.width,
            "height_px": rendered.height,
            "cropped": cropped,
        }


def _render_schematic_png_artifact(
    sch_file: Path,
    output_file: Path,
    *,
    dpi: int,
    crop_to_content: bool,
    include_title_block: bool,
) -> tuple[Path, dict[str, object]]:
    svg_dir = output_file.parent / "_svg"
    svg_dir.mkdir(parents=True, exist_ok=True)
    known_svg_files = set(svg_dir.glob("*.svg"))
    code, stdout, stderr = _export_schematic_svg_for_render(
        sch_file,
        svg_dir,
        include_title_block=include_title_block,
    )
    if code != 0:
        reason = stderr or stdout or "unknown error"
        raise RuntimeError(f"during SVG export: {reason}")
    svg_file = _latest_svg_file(svg_dir, known_svg_files)
    if svg_file is None:
        raise RuntimeError("kicad-cli did not produce an SVG file.")
    image_metadata = _render_svg_to_png(
        svg_file,
        output_file,
        dpi=dpi,
        crop_to_content=crop_to_content,
    )
    return svg_file, image_metadata


def _render_png_visual_diff(
    before_file: Path,
    after_file: Path,
    output_file: Path,
) -> dict[str, object]:
    try:
        from PIL import Image, ImageChops
    except ImportError as exc:
        raise RuntimeError(
            "Visual diff rendering requires Pillow. Install the project dev extras "
            "or run uv sync --all-extras --frozen."
        ) from exc

    with Image.open(before_file) as before_source, Image.open(after_file) as after_source:
        before = before_source.convert("RGBA")
        after = after_source.convert("RGBA")
        width = max(before.width, after.width)
        height = max(before.height, after.height)
        if before.size != (width, height):
            padded = Image.new("RGBA", (width, height), (255, 255, 255, 0))
            padded.alpha_composite(before)
            before = padded
        if after.size != (width, height):
            padded = Image.new("RGBA", (width, height), (255, 255, 255, 0))
            padded.alpha_composite(after)
            after = padded

        # Flatten onto white so alpha differences register as RGB differences.
        white = Image.new("RGBA", (width, height), (255, 255, 255, 255))
        before_flat = Image.alpha_composite(white.copy(), before).convert("RGB")
        after_flat = Image.alpha_composite(white.copy(), after).convert("RGB")
        delta = ImageChops.difference(before_flat, after_flat).convert("L")
        mask = delta.point(lambda value: 255 if value > 8 else 0)
        changed_pixels = mask.histogram()[255]
        faded = Image.blend(
            after,
            Image.new("RGBA", after.size, (255, 255, 255, 255)),
            0.22,
        )
        highlight = Image.new("RGBA", after.size, (239, 34, 74, 255))
        Image.composite(highlight, faded, mask).save(output_file)
        changed_bbox = mask.getbbox()

    return {
        "width_px": width,
        "height_px": height,
        "changed_pixels": changed_pixels,
        "changed_bbox_px": list(changed_bbox) if changed_bbox is not None else None,
    }


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
        "properties": _symbol_property_values(block),
        "dnp": _symbol_bool_flag(block, "dnp", default=False),
        "in_bom": _symbol_bool_flag(block, "in_bom", default=True),
        "x": float(at_match.group(1)) if at_match else 0.0,
        "y": float(at_match.group(2)) if at_match else 0.0,
        "rotation": int(round(float(at_match.group(3)))) if at_match else 0,
        "unit": int(unit_match.group(1)) if unit_match else 1,
    }


def _symbol_property_values(block: str) -> dict[str, str]:
    """Return every ``(property "name" "value")`` pair declared on a symbol."""
    return {
        _unescape_sexpr_string(match.group(1)): _unescape_sexpr_string(match.group(2))
        for match in re.finditer(
            rf"\(property\s+{_STRING_PATTERN}\s+{_STRING_PATTERN}",
            block,
        )
    }


def _symbol_bool_flag(block: str, flag: str, *, default: bool) -> bool:
    """Read a native ``(flag yes|no)`` toggle (e.g. ``dnp``, ``in_bom``)."""
    match = re.search(rf"\({re.escape(flag)}\s+(yes|no)\)", block)
    if match is None:
        return default
    return match.group(1) == "yes"


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


def _wire_endpoints(content: str) -> tuple[tuple[float, float], ...]:
    """Return both endpoints of every wire in the document."""
    points: list[tuple[float, float]] = []
    for wire in _extract_wires(content):
        points.append((wire["x1"], wire["y1"]))
        points.append((wire["x2"], wire["y2"]))
    return tuple(points)


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
    wires = _extract_wires(content)
    segments = _wire_segments_from_content(content)
    deduped = _deduplicate_segments(segments)
    if not deduped:
        return content
    uuid_map: dict[tuple[float, float, float, float], str] = {}
    for w in wires:
        key = (w["x1"], w["y1"], w["x2"], w["y2"])
        if "uuid" in w:
            uuid_map[key] = w["uuid"]
    updated = _remove_wire_blocks(content)
    for segment in deduped:
        uid = uuid_map.get(segment)
        updated = _append_before_sheet_instances(updated, wire_block(*segment, uuid_str=uid))
    return _insert_junctions_for_batch(updated, _detect_t_intersections(deduped))


def _extract_labels(content: str) -> list[dict[str, Any]]:
    labels: list[dict[str, Any]] = []
    for match in re.finditer(
        rf"\((?:label|global_label|hierarchical_label)\s+{_STRING_PATTERN}\s+"
        r"(?:\(shape\s+\w+\)\s+)?\(at\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\)",
        content,
    ):
        block, _ = _extract_block(content, match.start())
        labels.append(
            {
                "name": _unescape_sexpr_string(match.group(1)),
                "x": float(match.group(2)),
                "y": float(match.group(3)),
                "rotation": int(round(float(match.group(4)))),
                "justify": _label_justify_from_block(block) if block else "",
            }
        )
    return labels


def _label_justify_from_block(block: str) -> str:
    """Read the raw ``(justify ...)`` token string from a label block, if any."""
    justify_match = re.search(r"\(justify\s+([^)]*)\)", block)
    return justify_match.group(1).strip() if justify_match else ""


def _set_label_justify(block: str, justify_value: str) -> str:
    """Insert, replace, or remove the ``(justify ...)`` node inside a label's
    ``(effects ...)`` block. An empty ``justify_value`` removes any existing
    override, restoring KiCad's centered default."""
    idx = block.find("(effects")
    if idx == -1:
        return block
    effects_block, eff_len = _extract_block(block, idx)
    jidx = effects_block.find("(justify")
    if jidx != -1:
        _, jlen = _extract_block(effects_block, jidx)
        effects_block = effects_block[:jidx] + effects_block[jidx + jlen :]
        effects_block = re.sub(r"\s+\)", ")", effects_block)
    if justify_value:
        effects_block = effects_block[:-1].rstrip() + f" (justify {justify_value}))"
    return block[:idx] + effects_block + block[idx + eff_len :]


def _parse_label_block(block: str) -> dict[str, Any] | None:
    """Parse a single ``(label|global_label|hierarchical_label ...)`` block."""
    match = re.match(
        rf"\((label|global_label|hierarchical_label)\s+{_STRING_PATTERN}\s+"
        r"(?:\(shape\s+\w+\)\s+)?\(at\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\)",
        block,
    )
    if match is None:
        return None
    return {
        "kind": match.group(1),
        "name": _unescape_sexpr_string(match.group(2)),
        "x": float(match.group(3)),
        "y": float(match.group(4)),
        "rotation": int(round(float(match.group(5)))),
        "justify": _label_justify_from_block(block),
    }


def _schematic_object_map(content: str) -> dict[str, dict[str, Any]]:
    records: list[dict[str, Any]] = []

    cursor = 0
    while cursor < len(content):
        if content[cursor:].startswith("(symbol"):
            block, length = _extract_block(content, cursor)
            if block:
                parsed = _parse_symbol_block(block)
                if parsed is not None:
                    records.append({"kind": "symbol", **parsed})
                cursor += length
                continue
        cursor += 1

    for match in re.finditer(r"\((?:label|global_label|hierarchical_label)\b", content):
        block, _ = _extract_block(content, match.start())
        parsed = _parse_label_block(block)
        if parsed is not None:
            records.append(
                {
                    "kind": "label",
                    "label_type": parsed["kind"],
                    "name": parsed["name"],
                    "x": parsed["x"],
                    "y": parsed["y"],
                    "rotation": parsed["rotation"],
                }
            )

    for wire in _extract_wires(content):
        signature = _wire_signature(
            float(wire["x1"]),
            float(wire["y1"]),
            float(wire["x2"]),
            float(wire["y2"]),
        )
        records.append(
            {
                "kind": "wire",
                "start": list(signature[0]),
                "end": list(signature[1]),
            }
        )

    for bus in _extract_buses(content):
        signature = _wire_signature(bus["x1"], bus["y1"], bus["x2"], bus["y2"])
        records.append(
            {
                "kind": "bus",
                "start": list(signature[0]),
                "end": list(signature[1]),
            }
        )

    for kind in ("junction", "no_connect"):
        for match in re.finditer(
            rf"\({kind}\s+\(at\s+([-\d.]+)\s+([-\d.]+)\)",
            content,
        ):
            records.append(
                {
                    "kind": kind,
                    "x": float(match.group(1)),
                    "y": float(match.group(2)),
                }
            )

    title_block = _find_title_block(content)
    if title_block is not None:
        records.append({"kind": "document", "name": "title_block", "value": title_block[1]})
    paper_match = re.search(r"\(paper\b[^\n]*\)", content)
    if paper_match is not None:
        records.append({"kind": "document", "name": "paper", "value": paper_match.group(0)})

    grouped: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        kind = str(record["kind"])
        if kind == "symbol":
            base = f"symbol:{record['reference']}:unit={record['unit']}"
        elif kind == "label":
            base = f"label:{record['label_type']}:{record['name']}"
        elif kind in {"wire", "bus"}:
            base = f"{kind}:{record['start']}->{record['end']}"
        elif kind in {"junction", "no_connect"}:
            base = f"{kind}:{record['x']},{record['y']}"
        else:
            base = f"document:{record['name']}"
        grouped.setdefault(base, []).append(record)

    result: dict[str, dict[str, Any]] = {}
    for base, items in sorted(grouped.items()):
        ordered = sorted(items, key=lambda item: json.dumps(item, sort_keys=True))
        for index, item in enumerate(ordered, start=1):
            object_id = base if len(ordered) == 1 else f"{base}:occurrence={index}"
            result[object_id] = item
    return result


def _schematic_object_diff(before: str, after: str) -> list[dict[str, Any]]:
    before_objects = _schematic_object_map(before)
    after_objects = _schematic_object_map(after)
    changes: list[dict[str, Any]] = []
    for object_id in sorted(set(before_objects) | set(after_objects)):
        before_object = before_objects.get(object_id)
        after_object = after_objects.get(object_id)
        if before_object == after_object:
            continue
        if before_object is None:
            change = "added"
        elif after_object is None:
            change = "removed"
        else:
            change = "modified"
        source = after_object or before_object or {}
        changes.append(
            {
                "id": object_id,
                "kind": source.get("kind", "unknown"),
                "change": change,
                "before": before_object,
                "after": after_object,
            }
        )
    if not changes and before != after:
        changes.append(
            {
                "id": "document:schematic",
                "kind": "document",
                "change": "modified",
                "before": None,
                "after": None,
            }
        )
    return changes


def _visual_diff_state_names(sch_file: Path) -> tuple[str, str]:
    key = hashlib.sha256(str(sch_file.resolve()).encode("utf-8")).hexdigest()[:16]
    return f"visual-diff-{key}.json", f"visual-diff-{key}-before.kicad_sch"


def _record_schematic_visual_diff(sch_file: Path, before: str, after: str) -> None:
    state_name, snapshot_name = _visual_diff_state_names(sch_file)
    snapshot_path = _schematic_state_path(snapshot_name)
    snapshot_path.write_text(before, encoding="utf-8")
    changed_objects = _schematic_object_diff(before, after)
    changed_refs = sorted(
        {
            str(item.get("reference"))
            for change in changed_objects
            for item in (change.get("before"), change.get("after"))
            if isinstance(item, dict) and item.get("reference")
        }
    )
    changed_nets = sorted(
        {
            str(item.get("name"))
            for change in changed_objects
            for item in (change.get("before"), change.get("after"))
            if isinstance(item, dict) and item.get("kind") == "label" and item.get("name")
        }
    )
    _save_schematic_state(
        state_name,
        {
            "status": "ready",
            "schematic_path": str(sch_file.resolve()),
            "before_snapshot": str(snapshot_path),
            "before_sha256": hashlib.sha256(before.encode("utf-8")).hexdigest(),
            "after_sha256": hashlib.sha256(after.encode("utf-8")).hexdigest(),
            "changed_objects": changed_objects,
            "changed_refs": changed_refs,
            "changed_nets": changed_nets,
        },
    )


def _load_schematic_visual_diff(sch_file: Path) -> dict[str, Any] | None:
    state_name, _ = _visual_diff_state_names(sch_file)
    state_path = _schematic_state_path(state_name)
    if not state_path.is_file():
        return None
    payload = json.loads(state_path.read_text(encoding="utf-8"))
    return cast(dict[str, Any], payload)


def _get_schematic_file() -> Path:
    cfg = get_config()
    if cfg.sch_file is None or not cfg.sch_file.exists():
        raise ValueError(
            "No schematic file is configured. Call kicad_set_project() or set KICAD_MCP_SCH_FILE."
        )
    return cfg.sch_file


def _format_schematic_diagnostics(sch_file: Path) -> list[str]:
    """Render active schematic path diagnostics for file-backed read tools."""
    cfg = get_config()
    project_path = cfg.project_dir if cfg.project_dir is not None else "(not configured)"
    return [
        "Diagnostics:",
        "- Source: file-backed",
        f"- Active project path: {project_path}",
        f"- Schematic file: {sch_file}",
    ]


def _with_schematic_diagnostics(message: str, sch_file: Path) -> str:
    """Append active schematic diagnostics to an empty-state read response."""
    return "\n".join([message, *_format_schematic_diagnostics(sch_file)])


def project_schematic_files() -> list[Path]:
    """Return the active project's schematic files, including flat sibling sheets."""
    active = _get_schematic_file().resolve()
    cfg = get_config()
    root = cfg.project_file.parent if cfg.project_file is not None else active.parent
    if cfg.project_dir is not None:
        root = cfg.project_dir
    try:
        candidates = sorted(
            path.resolve()
            for path in root.glob("*.kicad_sch")
            if path.is_file() and not is_numbered_duplicate_kicad_file(path)
        )
    except OSError:
        candidates = []
    if active not in candidates and active.exists():
        candidates.insert(0, active)
    return candidates or [active]


def _sort_symbols_for_annotation(symbols: list[dict[str, Any]], order: str) -> None:
    """Order symbols in place for sequential reference annotation.

    ``sheet`` numbers top-to-bottom then left-to-right; ``left_to_right`` numbers
    left-to-right then top-to-bottom; everything else falls back to alphabetical
    by existing reference.
    """
    if order == "sheet":
        symbols.sort(key=lambda item: (item["y"], item["x"]))
    elif order == "left_to_right":
        symbols.sort(key=lambda item: (item["x"], item["y"]))
    else:
        symbols.sort(key=lambda item: item["reference"])


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
    _sort_symbols_for_annotation(symbols, payload.order)

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


def _schematic_project_dir() -> Path | None:
    cfg = get_config()
    if cfg.project_file is not None:
        return cfg.project_file.parent
    if cfg.project_dir is not None:
        return cfg.project_dir
    return None


def _resolve_kicad_table_uri(uri: str, project_dir: Path | None) -> str:
    def _sub(match: re.Match[str]) -> str:
        name = match.group(1)
        if name == "KIPRJMOD" and project_dir is not None:
            return str(project_dir)
        return os.environ.get(name, match.group(0))

    return re.sub(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", _sub, uri)


def _project_symbol_library_files() -> dict[str, Path]:
    project_dir = _schematic_project_dir()
    if project_dir is None:
        return {}
    table = project_dir / "sym-lib-table"
    try:
        content = table.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return {}

    files: dict[str, Path] = {}
    for chunk in re.split(r"\(lib\b", content)[1:]:
        name = re.search(r'\(name\s+"?([^")\s]+)"?\)', chunk)
        type_ = re.search(r'\(type\s+"?([^")\s]+)"?\)', chunk)
        uri = re.search(r'\(uri\s+"([^"]+)"\)', chunk)
        if not (name and uri):
            continue
        if type_ and type_.group(1).lower() != "kicad":
            continue
        resolved = Path(_resolve_kicad_table_uri(uri.group(1), project_dir))
        if resolved.exists():
            files.setdefault(name.group(1), resolved)
    return files


def _symbol_library_file(library: str) -> Path | None:
    try:
        configured = _get_symbol_library_dir() / f"{library}.kicad_sym"
    except FileNotFoundError:
        configured = None
    if configured is not None and configured.exists():
        return configured
    project_file = _project_symbol_library_files().get(library)
    if project_file is not None and project_file.exists():
        return project_file
    return None


def rotate_point(x: float, y: float, angle_deg: float) -> tuple[float, float]:
    """Rotate a point around the origin."""
    radians = math.radians(angle_deg)
    cos_a = math.cos(radians)
    sin_a = math.sin(radians)
    return (round(x * cos_a - y * sin_a, 4), round(x * sin_a + y * cos_a, 4))


def load_lib_symbol(library: str, symbol_name: str) -> str | None:
    """Load a symbol definition from a KiCad symbol library.

    Plain symbols are returned with their top-level name qualified by the
    library prefix. Derived ``(extends ...)`` symbols are *flattened* into a
    single self-contained symbol -- the way KiCad caches symbols inside a
    schematic -- so the embedded body/pins render at exactly the coordinates
    ``get_pin_positions`` reports. (Embedding the raw extends form instead left
    the derived symbol's pins rendered off their reported positions, so labels
    placed on them dangled in ERC.)
    """
    sym_file = _symbol_library_file(library)
    if sym_file is None:
        return None

    content = sym_file.read_text(encoding="utf-8", errors="ignore")
    blocks = _collect_symbol_blocks(content, symbol_name)
    if not blocks:
        return None

    if len(blocks) == 1:
        block = blocks[0]
        block_name = _symbol_block_name(block)
        if block_name is not None and not block_name.startswith(f"{library}:"):
            block = block.replace(f'(symbol "{block_name}"', f'(symbol "{library}:{block_name}"', 1)
        return block

    return _flatten_extends_symbol(library, symbol_name, blocks)


def _flatten_extends_symbol(library: str, symbol_name: str, blocks: list[str]) -> str:
    """Collapse an ``(extends ...)`` chain into one self-contained symbol.

    KiCad does not keep the extends relationship when it caches a symbol inside a
    schematic: it copies the base symbol's graphic child units into the derived
    symbol and renames them to the derived symbol's prefix. We reproduce that so
    the embedded derived symbol behaves like a normal (non-derived) symbol and
    its pins land where ``get_pin_positions`` reports.
    """
    # The base is the nearest ancestor that actually defines body/pin child
    # units; _collect_symbol_blocks returns ancestors first, the derived last.
    base = blocks[0]
    base_name = _symbol_block_name(base) or ""
    for block in blocks:
        if _extract_child_symbol_blocks(block):
            base = block
            base_name = _symbol_block_name(block) or ""
            break

    flat = base
    # Re-prefix the graphic child units (e.g. "BASE_0_1" -> "DERIVED_0_1") so
    # KiCad associates them with the flattened, derived-named symbol.
    if base_name and base_name != symbol_name:
        flat = flat.replace(f'(symbol "{base_name}_', f'(symbol "{symbol_name}_')
    # Qualify the top-level symbol name with the library prefix and derived name.
    if base_name:
        flat = flat.replace(f'(symbol "{base_name}"', f'(symbol "{library}:{symbol_name}"', 1)
    # Override inherited properties (Value, Footprint, Datasheet, ...) with the
    # derived symbol's own values so the flattened symbol matches KiCad's library.
    base_props = _symbol_property_blocks(base)
    for prop_name, derived_prop in _symbol_property_blocks(blocks[-1]).items():
        base_prop = base_props.get(prop_name)
        if base_prop and base_prop in flat:
            flat = flat.replace(base_prop, derived_prop, 1)
    return flat


def _symbol_property_blocks(block: str) -> dict[str, str]:
    """Return ``{property_name: "(property ...)" block}`` for a symbol's own
    top-level properties (nested child sub-symbols are ignored)."""
    shell = _strip_child_symbol_blocks(block)
    props: dict[str, str] = {}
    cursor = 0
    while True:
        idx = shell.find('(property "', cursor)
        if idx < 0:
            break
        prop_block, consumed = _extract_block(shell, idx)
        cursor = idx + max(consumed, 1)
        if not prop_block:
            continue
        match = re.match(r'\(property\s+"([^"]+)"', prop_block)
        if match:
            props.setdefault(match.group(1), prop_block)
    return props


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
    cursor = 0
    while cursor < len(block):
        pin_start = block.find("(pin", cursor)
        if pin_start < 0:
            break
        pin_block, consumed = _extract_block(block, pin_start)
        cursor = pin_start + max(consumed, 1)
        if not pin_block:
            continue
        at_match = re.search(
            r"\(at\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\)",
            pin_block,
        )
        number_match = re.search(r'\(number\s+"([^"]+)"', pin_block)
        if at_match is None or number_match is None:
            continue
        name_match = re.search(r'\(name\s+"([^"]*)"', pin_block)
        # The electrical type is the first token after "(pin", e.g. "(pin power_in line".
        etype_match = re.match(r"\(pin\s+([a-z_]+)\b", pin_block)
        records.append(
            {
                "x": float(at_match.group(1)),
                "y": float(at_match.group(2)),
                "name": name_match.group(1) if name_match else "",
                "number": number_match.group(1),
                "etype": etype_match.group(1) if etype_match else "unspecified",
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
    """Return ``{alias: position}`` for a symbol block's pins.

    Exact identifiers (pin number, pin name, and their case-folds) use *keep the
    first occurrence* semantics: a connector that repeats a name across contacts
    of the same signal (a USB-C receptacle exposes ``D+``/``D-`` on two contacts
    each) still resolves that name instead of being dropped as ambiguous. Only
    the *normalized* aliases (which fold ``D+`` and ``D-`` both to ``d``) are
    conflict-dropped, so a genuinely ambiguous fuzzy match never mis-resolves.
    """
    exact: dict[str, tuple[float, float]] = {}
    fuzzy: dict[str, tuple[float, float]] = {}
    fuzzy_conflicts: set[str] = set()
    for record in _extract_pin_records(block):
        rx, ry = rotate_point(float(record["x"]), -float(record["y"]), rotation)
        point = (round(sym_x + rx, 4), round(sym_y + ry, 4))
        number = str(record["number"])
        name = str(record["name"])
        for identifier in (number, name, number.casefold(), name.casefold()):
            if identifier:
                exact.setdefault(identifier, point)
        for alias in (_normalize_pin_alias(number), _normalize_pin_alias(name)):
            _merge_pin_alias(fuzzy, fuzzy_conflicts, alias, point)
    for alias in fuzzy_conflicts:
        fuzzy.pop(alias, None)
    merged = dict(fuzzy)
    merged.update(exact)  # exact identifiers win over normalized aliases
    return merged


def _available_units_from_blocks(blocks: list[str]) -> set[int]:
    units: set[int] = set()
    has_pins = False
    for block in blocks:
        if _extract_pin_definitions(_strip_child_symbol_blocks(block)):
            has_pins = True
        block_name = _symbol_block_name(block)
        if block_name is None:
            continue
        prefix = f"{block_name}_"
        for child_name, child_block in _extract_child_symbol_blocks(block):
            if not child_name.startswith(prefix):
                continue
            unit_str, _, _ = child_name[len(prefix) :].partition("_")
            if unit_str.isdigit():
                unit_value = int(unit_str)
                if unit_value >= 1:
                    units.add(unit_value)
                elif _extract_pin_definitions(child_block):
                    # Unit-0 sub-symbol holds pins common to all units, e.g.
                    # single-unit easyeda2kicad imports place every pin there.
                    has_pins = True
    if not units and has_pins:
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
    sym_file = _symbol_library_file(library)
    if sym_file is None:
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
            pins[pin_number] = (round(sym_x + rx, 4), round(sym_y + ry, 4))

        block_name = _symbol_block_name(block)
        if block_name is None:
            continue
        # Match the requested unit and unit 0 (pins common to all units, where
        # single-unit easyeda2kicad imports place every pin).
        unit_prefixes = (f"{block_name}_{unit}_", f"{block_name}_0_")
        for child_name, child_block in _extract_child_symbol_blocks(block):
            if not child_name.startswith(unit_prefixes):
                continue
            for pin_number, (px, py) in _extract_pin_definitions(child_block).items():
                # KiCad's pin (at x y angle) coordinate is the electrical connection point.
                rx, ry = rotate_point(px, -py, rotation)
                pins[pin_number] = (round(sym_x + rx, 4), round(sym_y + ry, 4))
    return pins


def get_pin_metadata(
    library: str,
    symbol_name: str,
    unit: int = 1,
    *,
    sch_dir: Path | None = None,
) -> dict[str, dict[str, str]]:
    """Return ``{pin_number: {"name", "etype"}}`` for a symbol's pins.

    Mirrors :func:`get_pin_positions`' block/unit traversal but carries the pin
    name and electrical type so design-rule checks can reason about power, input,
    and no-connect pins rather than only geometry.

    ``sch_dir`` is an optional fallback directory; if the library is not found
    via the global config, the function also checks ``<sch_dir>/symbols/``.
    """
    sym_file = _symbol_library_file(library)
    if sym_file is None and sch_dir is not None:
        fallback = sch_dir / "symbols" / f"{library}.kicad_sym"
        if fallback.exists():
            sym_file = fallback
    if sym_file is None:
        return {}
    content = sym_file.read_text(encoding="utf-8", errors="ignore")
    blocks = _collect_symbol_blocks(content, symbol_name)
    if not blocks:
        return {}
    available_units = _available_units_from_blocks(blocks)
    if available_units and unit not in available_units:
        return {}

    meta: dict[str, dict[str, str]] = {}

    def _record(record: dict[str, Any]) -> None:
        meta[record["number"]] = {
            "name": str(record.get("name", "")),
            "etype": str(record.get("etype", "unspecified")),
        }

    for block in blocks:
        for record in _extract_pin_records(_strip_child_symbol_blocks(block)):
            _record(record)
        block_name = _symbol_block_name(block)
        if block_name is None:
            continue
        unit_prefixes = (f"{block_name}_{unit}_", f"{block_name}_0_")
        for child_name, child_block in _extract_child_symbol_blocks(block):
            if not child_name.startswith(unit_prefixes):
                continue
            for record in _extract_pin_records(child_block):
                _record(record)
    return meta


def _pin_label_stub_direction(
    pin_point: tuple[float, float],
    symbol_origin: tuple[float, float],
    all_pin_points: Iterable[tuple[float, float]],
) -> tuple[float, float]:
    """Return an outward unit vector for a pin-label stub.

    Dense/tall symbols such as MCU modules often have side pins whose
    vertical distance from the symbol origin is larger than their horizontal
    distance.  Using the origin as a dominant-axis proxy makes those side pins
    stub vertically, which can overlap adjacent side-pin stubs and short nets.

    Prefer the actual outer pin extents: pins on the left/right edge stub
    horizontally, pins on the top/bottom edge stub vertically.  Fall back to
    the historical origin-based dominant axis only for interior pins or
    degenerate one-dimensional symbols.
    """
    px, py = pin_point
    ox, oy = symbol_origin
    points = list(all_pin_points)
    if points:
        xs = [x for x, _ in points]
        ys = [y for _, y in points]
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
        # Pin coordinates are rounded to 1e-4 mm by get_pin_positions().  Use a
        # small tolerance so grid/rotation floating point noise cannot flip a
        # true edge pin into the origin fallback.
        edge_tol = 1e-3
        x_span = max_x - min_x
        y_span = max_y - min_y
        # A single-column connector has every pin on the same X coordinate.  The
        # top/bottom pins are geometric extrema, but routing them vertically makes
        # their terminal stubs run through neighbouring pins and can short nets.
        # Treat one-dimensional vertical pin rows as side pins and stub away from
        # the symbol body instead.
        if x_span <= edge_tol and y_span > edge_tol:
            return ((1.0 if px >= ox else -1.0), 0.0)
        # Conversely, a single-row connector should not have left/right extrema
        # stub horizontally through neighbouring pins.
        if y_span <= edge_tol and x_span > edge_tol:
            return (0.0, (1.0 if py >= oy else -1.0))
        if x_span > edge_tol:
            if abs(px - min_x) <= edge_tol:
                return (-1.0, 0.0)
            if abs(px - max_x) <= edge_tol:
                return (1.0, 0.0)
        if y_span > edge_tol:
            if abs(py - min_y) <= edge_tol:
                return (0.0, -1.0)
            if abs(py - max_y) <= edge_tol:
                return (0.0, 1.0)

    dx, dy = px - ox, py - oy
    if abs(dx) >= abs(dy):
        return ((1.0 if dx >= 0 else -1.0), 0.0)
    return (0.0, (1.0 if dy >= 0 else -1.0))


def get_pin_alias_positions(
    library: str,
    symbol_name: str,
    sym_x: float,
    sym_y: float,
    rotation: int = 0,
    unit: int = 1,
) -> dict[str, tuple[float, float]]:
    """Return a lookup for pin numbers, names, and normalized aliases."""
    sym_file = _symbol_library_file(library)
    if sym_file is None:
        return {}

    content = sym_file.read_text(encoding="utf-8", errors="ignore")
    blocks = _collect_symbol_blocks(content, symbol_name)
    if not blocks:
        return {}
    available_units = _available_units_from_blocks(blocks)
    if available_units and unit not in available_units:
        return {}

    # Each block already resolves its own exact/normalized aliases; merge blocks
    # with keep-first so a name resolved in one block is not dropped by a repeat
    # in another.
    aliases: dict[str, tuple[float, float]] = {}
    for block in blocks:
        for alias, point in _pin_alias_positions(
            _strip_child_symbol_blocks(block),
            sym_x,
            sym_y,
            rotation,
        ).items():
            aliases.setdefault(alias, point)

        block_name = _symbol_block_name(block)
        if block_name is None:
            continue
        # Match the requested unit and unit 0 (pins common to all units, where
        # single-unit easyeda2kicad imports place every pin).
        unit_prefixes = (f"{block_name}_{unit}_", f"{block_name}_0_")
        for child_name, child_block in _extract_child_symbol_blocks(block):
            if not child_name.startswith(unit_prefixes):
                continue
            for alias, point in _pin_alias_positions(
                child_block,
                sym_x,
                sym_y,
                rotation,
            ).items():
                aliases.setdefault(alias, point)

    return aliases


def get_symbol_available_units(library: str, symbol_name: str) -> set[int]:
    """Return supported symbol units from the KiCad library."""
    sym_file = _symbol_library_file(library)
    if sym_file is None:
        return set()

    content = sym_file.read_text(encoding="utf-8", errors="ignore")
    blocks = _collect_symbol_blocks(content, symbol_name)
    if not blocks:
        return set()
    return _available_units_from_blocks(blocks)


def symbol_exists(library: str, symbol_name: str) -> bool | None:
    """Return whether ``library:symbol_name`` is present in the library.

    ``None`` means the library file itself could not be located by this headless
    reader, so callers must NOT treat the symbol as missing (it may resolve via a
    library table this reader does not see). ``False`` means the library was found
    but does not contain the symbol — a genuine "not found".
    """
    sym_file = _symbol_library_file(library)
    if sym_file is None:
        return None
    content = sym_file.read_text(encoding="utf-8", errors="ignore")
    return bool(_collect_symbol_blocks(content, symbol_name))


def suggest_symbol_names(library: str, symbol_name: str, *, limit: int = 3) -> list[str]:
    """Return up to ``limit`` close top-level symbol names from ``library``.

    Used to turn a wrong/non-existent symbol name into an actionable hint (e.g.
    ``USB_C_Receptacle_USB2.0`` -> ``USB_C_Receptacle_USB2.0_16P``).
    """
    sym_file = _symbol_library_file(library)
    if sym_file is None:
        return []
    content = sym_file.read_text(encoding="utf-8", errors="ignore")
    tops = [
        name
        for name in re.findall(r'\(symbol\s+"([^"]+)"', content)
        if not re.search(r"_\d+_\d+$", name)  # drop graphic child-unit symbols
    ]
    target = symbol_name.lower()

    def _score(name: str) -> int:
        low = name.lower()
        if low == target:
            return 0
        if low.startswith(target) or target.startswith(low):
            return 1
        # longest shared prefix length (higher = closer); negate for ascending sort
        shared = 0
        for a, b in zip(low, target, strict=False):
            if a != b:
                break
            shared += 1
        return 100 - shared if shared >= 4 else 999

    scored = sorted(((_score(n), n) for n in tops), key=lambda t: (t[0], t[1]))
    return [name for score, name in scored if score < 999][:limit]


def _validate_symbol_resolves(library: str, symbol_name: str) -> None:
    """Raise a clear error if ``library:symbol_name`` is provably missing.

    No-op when the library cannot be located (``symbol_exists`` returns ``None``)
    so symbols from library tables this reader does not see are not false-rejected.
    """
    if symbol_exists(library, symbol_name) is False:
        suggestions = suggest_symbol_names(library, symbol_name)
        hint = f" Did you mean: {', '.join(suggestions)}?" if suggestions else ""
        raise ValueError(
            f"Symbol '{library}:{symbol_name}' was not found in library '{library}'. "
            f"Search with lib_search_symbols and use the exact symbol name.{hint}"
        )


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
    if (
        _is_power_net(name)
        and name.upper() in power_points
        and not any(_endpoint_power(endpoint) for endpoint in endpoints)
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


def _terminal_stub_length(net_name: str) -> float:
    """Grid-snapped terminal-stub length that scales with the net-name width.

    A global label's text extends outward from the stub end, so a long net name
    on a fixed short stub renders its text on top of the symbol body / pin names.
    Pushing the label further out (by roughly half the rendered text width, on the
    2.54 mm grid) keeps it clear. Short names keep the historical 5.08 mm stub.
    """
    width_mm, _ = text_extent(net_name)
    needed = 5.08 + max(0.0, width_mm - 5.08) * 0.5
    grid = SCHEMATIC_GRID_MM
    return max(5.08, math.ceil(needed / grid) * grid)


def _terminal_rotation_from_vector(ux: float, uy: float) -> int:
    return 0 if ux > 0 else 180 if ux < 0 else 90 if uy < 0 else 270


def _power_symbol_rotation_from_vector(ux: float, uy: float) -> int:
    """Orient a power symbol outward from the connected pin stub."""
    if uy > 0:
        return 0
    if uy < 0:
        return 180
    if ux > 0:
        return 270
    return 90


def _terminal_label_spec(
    net_name: str,
    x_mm: float,
    y_mm: float,
    rotation: int,
    label_kind: str | None,
    shape: str | None,
) -> dict[str, Any]:
    """Build a terminal-label spec, honoring an optional per-net label kind.

    With no explicit ``label_kind`` (net ``scope`` omitted) this preserves the
    historical default: a bidirectional global label.  ``local`` / ``global`` /
    ``hierarchical`` scopes select the matching label kind instead.
    """
    spec: dict[str, Any] = {
        "name": net_name,
        "x_mm": x_mm,
        "y_mm": y_mm,
        "rotation": rotation,
        "snap_to_grid": False,
    }
    if label_kind is None:
        spec["global_label"] = True
        spec["shape"] = "bidirectional"
        return spec
    spec["kind"] = label_kind
    if label_kind == "hierarchical_label":
        spec["shape"] = shape or "bidirectional"
    return spec


def _plan_netlist_pin_terminals(
    symbols: list[AddSymbolInput],
    powers: list[PowerSymbolInput],
    labels: list[AddLabelInput],
    nets: list[dict[str, Any]],
    snap_to_grid: bool,
) -> tuple[
    list[dict[str, float | bool]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    dict[str, int],
]:
    """Plan collision-safe per-pin net terminals for netlist auto-layout.

    Netlist-aware auto-layout must not draw long routed wires between arbitrary
    pins.  A routed Manhattan star can cross unrelated pins or labels and KiCad
    will merge by geometry.  Instead, each pin endpoint gets a short outward stub
    plus a same-named terminal.  Signal nets use global labels; power nets use
    conventional power symbols.  Same-named terminals connect by name rather than
    by accidental wire geometry.
    """
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

    # Pin electrical types, keyed by number/name/case-fold, so a net's driver
    # status can be judged: KiCad's plain power symbols (power:+3V3, power:GND)
    # are power_in, so a rail with only power_in pins and no power_out source
    # needs a PWR_FLAG or ERC reports "input power pin not driven".
    pin_etypes: dict[str, dict[str, str]] = {}
    for symbol in symbols:
        emap: dict[str, str] = {}
        for number, info in get_pin_metadata(
            symbol.library, symbol.symbol_name, symbol.unit
        ).items():
            etype = str(info.get("etype", ""))
            name = str(info.get("name", ""))
            for key in (number, name, number.casefold(), name.casefold()):
                if key:
                    emap.setdefault(key, etype)
        pin_etypes[symbol.reference] = emap

    power_points: dict[str, tuple[float, float]] = {}
    for power in powers:
        x, y = _snap_point(power.x_mm, power.y_mm, snap_to_grid and power.snap_to_grid)
        power_points.setdefault(power.name.upper(), (x, y))

    label_points: dict[str, tuple[float, float]] = {}
    for label in labels:
        x, y = _snap_point(label.x_mm, label.y_mm, snap_to_grid and label.snap_to_grid)
        label_points.setdefault(label.name, (x, y))

    terminal_wires: list[dict[str, float | bool]] = []
    terminal_labels: list[dict[str, Any]] = []
    terminal_powers: list[dict[str, Any]] = []
    unresolved_nets: list[dict[str, Any]] = []
    terminal_points: dict[tuple[float, float], str] = {}
    pin_points_seen: dict[tuple[float, float], str] = {}
    net_has_power_out: dict[str, bool] = {}
    net_needs_driver: dict[str, bool] = {}
    net_names_seen: set[str] = set()
    net_terminal_max_y = AUTO_LAYOUT_ORIGIN_Y_MM
    resolution_stats = {
        "resolved_endpoints": 0,
        "unresolved_endpoints": 0,
        "pin_alias_resolutions": 0,
        "symbol_center_resolutions": 0,
    }

    net_label_kinds: dict[str, str | None] = {}
    net_label_shapes: dict[str, str | None] = {}
    for net in nets:
        net_name = _net_name(net)
        label_kind = _net_label_kind(net)
        net_label_kinds[net_name] = label_kind
        net_shape = net.get("shape") if label_kind == "hierarchical_label" else None
        net_label_shapes[net_name] = net_shape
        endpoints = _net_endpoints(net)
        unresolved_endpoints: list[str] = []
        unresolved_details: list[str] = []
        generated_terminal_count = 0
        for endpoint in endpoints:
            reference = _endpoint_reference(endpoint)
            if reference is None:
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
                else:
                    resolution_stats["resolved_endpoints"] += 1
                    if resolution_kind == "pin_alias":
                        resolution_stats["pin_alias_resolutions"] += 1
                    elif resolution_kind == "symbol_center":
                        resolution_stats["symbol_center_resolutions"] += 1
                continue

            point, reason, resolution_kind = _resolve_net_endpoint(
                endpoint,
                net_name,
                symbol_points,
                symbol_pin_aliases,
                symbol_centers,
                power_points,
                label_points,
            )
            endpoint_text = _describe_net_endpoint(endpoint)
            if point is None:
                unresolved_endpoints.append(endpoint_text)
                unresolved_details.append(f"{endpoint_text}: {reason or 'unresolved endpoint'}")
                resolution_stats["unresolved_endpoints"] += 1
                continue
            if resolution_kind == "symbol_center":
                unresolved_endpoints.append(endpoint_text)
                unresolved_details.append(
                    f"{endpoint_text}: pin is required for collision-safe auto-layout terminals"
                )
                resolution_stats["unresolved_endpoints"] += 1
                continue

            pin_key = _point_key(*point)
            existing_pin_net = pin_points_seen.get(pin_key)
            if existing_pin_net is not None and existing_pin_net != net_name:
                unresolved_endpoints.append(endpoint_text)
                unresolved_details.append(
                    f"{endpoint_text}: pin point already assigned to net '{existing_pin_net}'"
                )
                resolution_stats["unresolved_endpoints"] += 1
                continue
            pin_points_seen[pin_key] = net_name

            pin_id = _endpoint_pin(endpoint)
            etype = pin_etypes.get(reference, {}).get(pin_id, "") if pin_id else ""
            if etype == "power_out":
                net_has_power_out[net_name] = True
            elif etype == "power_in":
                net_needs_driver.setdefault(net_name, True)

            all_points = symbol_points.get(reference, {}).values()
            ux, uy = _pin_label_stub_direction(point, symbol_centers[reference], all_points)
            stub = _terminal_stub_length(net_name)
            ex = round(point[0] + ux * stub, 4)
            ey = round(point[1] + uy * stub, 4)
            net_terminal_max_y = max(net_terminal_max_y, ey)
            end_key = _point_key(ex, ey)
            existing_terminal_net = terminal_points.get(end_key)
            if existing_terminal_net is not None and existing_terminal_net != net_name:
                unresolved_endpoints.append(endpoint_text)
                unresolved_details.append(
                    f"{endpoint_text}: terminal coordinate collides with net "
                    f"'{existing_terminal_net}'"
                )
                resolution_stats["unresolved_endpoints"] += 1
                continue
            terminal_points[end_key] = net_name

            terminal_wires.append(
                {
                    "x1_mm": point[0],
                    "y1_mm": point[1],
                    "x2_mm": ex,
                    "y2_mm": ey,
                    "snap_to_grid": False,
                }
            )
            rotation = _terminal_rotation_from_vector(ux, uy)
            if _should_place_power_terminal_symbol(net_name):
                terminal_powers.append(
                    {"name": net_name, "x_mm": ex, "y_mm": ey, "rotation": 0, "snap_to_grid": False}
                )
            else:
                terminal_labels.append(
                    _terminal_label_spec(
                        net_name,
                        ex,
                        ey,
                        rotation,
                        net_label_kinds[net_name],
                        net_label_shapes[net_name],
                    )
                )
            generated_terminal_count += 1
            net_names_seen.add(net_name)
            resolution_stats["resolved_endpoints"] += 1
            if resolution_kind == "pin_alias":
                resolution_stats["pin_alias_resolutions"] += 1

        if generated_terminal_count == 0 or unresolved_endpoints:
            unresolved_nets.append(
                {
                    "name": net_name or "<unnamed>",
                    "endpoint_count": len(endpoints),
                    "resolved_count": generated_terminal_count,
                    "unresolved_endpoints": unresolved_endpoints,
                    "unresolved_details": unresolved_details,
                }
            )

    # Auto PWR_FLAG: a power rail whose only power pins are power_in (its own
    # power symbol, IC supply pins) and that no power_out source drives would fail
    # ERC's "input power pin not driven" check. Add one PWR_FLAG (a power_out
    # symbol) per such rail, connected by name via a co-located global label, in a
    # strip clear of the placed terminals. Rails already driven by a regulator
    # output (power_out) are left untouched so real "undriven" errors still show.
    flag_nets = sorted(
        net_name
        for net_name in net_names_seen
        if (net_needs_driver.get(net_name) or _should_place_power_terminal_symbol(net_name))
        and not net_has_power_out.get(net_name)
    )
    flag_x = AUTO_LAYOUT_ORIGIN_X_MM
    flag_y = round(net_terminal_max_y + NETLIST_LAYOUT_ROW_SPACING_MM, 4)
    for net_name in flag_nets:
        fx, fy = _snap_point(flag_x, flag_y, True)
        terminal_powers.append(
            {"name": "PWR_FLAG", "x_mm": fx, "y_mm": fy, "rotation": 0, "snap_to_grid": False}
        )
        terminal_labels.append(
            _terminal_label_spec(
                net_name,
                fx,
                fy,
                0,
                net_label_kinds.get(net_name),
                net_label_shapes.get(net_name),
            )
        )
        flag_x += NETLIST_LAYOUT_COLUMN_SPACING_MM

    return terminal_wires, terminal_powers, terminal_labels, unresolved_nets, resolution_stats


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
    unsafe_routed_wires: bool = False,
    paper: str = "A4",
    max_paper: str = "A3",
) -> tuple[
    list[AddSymbolInput],
    list[PowerSymbolInput],
    list[AddLabelInput],
    list[AddWireInput],
    list[dict[str, Any]],
    list[dict[str, float | bool]],
    list[dict[str, Any]],
    dict[str, int],
    str,
]:
    if max_paper not in _PAPER_LADDER:
        raise ValueError(
            f"Invalid max_paper {max_paper!r}. Expected one of {', '.join(_PAPER_LADDER)}."
        )
    raw_symbols = [dict(item) for item in (symbols or [])]
    raw_powers = [dict(item) for item in (power_symbols or [])]
    raw_labels = [dict(item) for item in (labels or [])]
    raw_wires = [dict(item) for item in (wires or [])]
    raw_nets = [dict(item) for item in (nets or [])]
    chosen_paper = paper if paper in _PAPER_LADDER else "A4"
    if auto_layout:
        if raw_nets:
            raw_symbols, raw_powers, raw_labels, chosen_paper = _apply_netlist_auto_layout(
                raw_symbols,
                raw_powers,
                raw_labels,
                raw_nets,
                paper=chosen_paper,
                max_paper=max_paper,
            )
        else:
            raw_symbols, raw_powers, raw_labels, chosen_paper = _apply_basic_auto_layout(
                raw_symbols,
                raw_powers,
                raw_labels,
                paper=chosen_paper,
                max_paper=max_paper,
            )

    validated_symbols = [AddSymbolInput.model_validate(item) for item in raw_symbols]
    validated_powers = [PowerSymbolInput.model_validate(item) for item in raw_powers]
    validated_wires = [AddWireInput.model_validate(item) for item in raw_wires]
    validated_labels = [AddLabelInput.model_validate(item) for item in raw_labels]
    for symbol in validated_symbols:
        _validate_symbol_resolves(symbol.library, symbol.symbol_name)
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
        if not unsafe_routed_wires:
            # Default, collision-safe path: each pin endpoint gets a short outward
            # stub plus a same-named terminal (global label / power symbol), so nets
            # connect by name rather than by accidental wire geometry. This is the
            # default regardless of auto_layout — only the explicit opt-in below
            # falls back to routed wires that can short by crossing geometry.
            generated_powers: list[dict[str, Any]]
            generated_labels: list[dict[str, Any]]
            (
                generated_wires,
                generated_powers,
                generated_labels,
                unresolved_nets,
                resolution_stats,
            ) = _plan_netlist_pin_terminals(
                validated_symbols,
                validated_powers,
                validated_labels,
                raw_nets,
                snap_to_grid,
            )
            validated_powers.extend(
                PowerSymbolInput.model_validate(item) for item in generated_powers
            )
            validated_labels.extend(AddLabelInput.model_validate(item) for item in generated_labels)
        else:
            # Opt-in only: routed Manhattan star wires. These can cross unrelated
            # pins/labels and merge by geometry into silent shorts, so this path is
            # gated behind unsafe_routed_wires=True.
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
        chosen_paper,
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
    terminalized: bool = True,
) -> str:
    lines = ["Net compilation analysis:"]
    routing_mode = "terminal labels (collision-safe)" if terminalized else "routed wires (unsafe)"
    lines.extend(
        [
            f"- Symbols: {len(symbols)}",
            f"- Power symbols: {len(powers)}",
            f"- Labels: {len(labels)}",
            f"- Explicit wires supplied: {explicit_wires}",
            f"- Nets requested: {len(nets)}",
            f"- Routable nets: {len(nets) - len(unresolved_nets)}",
            f"- Unresolved nets: {len(unresolved_nets)}",
            (
                f"- Generated {'terminal stubs' if terminalized and nets else 'wire segments'}: "
                f"{len(generated_wires)}"
            ),
            f"- Net routing mode: {routing_mode}",
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


def _extract_no_connects(content: str) -> set[tuple[float, float]]:
    """Return schematic points carrying an explicit no-connect marker."""
    points: set[tuple[float, float]] = set()
    for match in re.finditer(
        r"\(no_connect\s+\(at\s+([-\d.]+)\s+([-\d.]+)",
        content,
    ):
        points.add(_point_key(float(match.group(1)), float(match.group(2))))
    return points


def _parse_no_connect_block(block: str) -> dict[str, Any] | None:
    """Parse a single ``(no_connect (at X Y) ...)`` block into its coordinate."""
    match = re.match(
        r"\(no_connect\s+\(at\s+([-\d.]+)\s+([-\d.]+)",
        block,
    )
    if match is None:
        return None
    return {"x": float(match.group(1)), "y": float(match.group(2))}


def _build_connectivity_groups(sch_file: Path) -> list[dict[str, Any]]:
    data = parse_schematic_file(sch_file)
    try:
        no_connect_points = _extract_no_connects(sch_file.read_text(encoding="utf-8"))
    except OSError:
        no_connect_points = set()
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
                "no_connect": False,
            },
        )

    for wire in data["wires"]:
        group = ensure_group(_point_key(wire["x1"], wire["y1"]))
        group["points"].add(_point_key(wire["x1"], wire["y1"]))
        group["points"].add(_point_key(wire["x2"], wire["y2"]))

    for point in no_connect_points:
        group = ensure_group(point)
        group["points"].add(point)
        group["no_connect"] = True

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
        pin_meta = get_pin_metadata(library, symbol_name, int(symbol["unit"]))
        for pin_number, point in pin_positions.items():
            group = ensure_group(point)
            group["points"].add(_point_key(*point))
            meta = pin_meta.get(pin_number, {})
            group["pins"].append(
                {
                    "reference": symbol["reference"],
                    "pin": pin_number,
                    "value": symbol["value"],
                    "name": meta.get("name", ""),
                    "etype": meta.get("etype", "unspecified"),
                }
            )

    name_roots: dict[str, tuple[float, float]] = {}
    for root, group in list(groups.items()):
        for name in {*group["labels"], *group["power"]}:
            if name in name_roots:
                union(name_roots[name], root)
            else:
                name_roots[name] = root

    collapsed_groups: dict[tuple[float, float], dict[str, Any]] = {}
    for root, group in groups.items():
        collapsed_root = find(root)
        merged = collapsed_groups.setdefault(
            collapsed_root,
            {
                "points": set(),
                "labels": set(),
                "power": set(),
                "pins": [],
                "no_connect": False,
            },
        )
        merged["points"].update(group["points"])
        merged["labels"].update(group["labels"])
        merged["power"].update(group["power"])
        merged["pins"].extend(group["pins"])
        merged["no_connect"] = bool(merged["no_connect"] or group.get("no_connect"))

    normalized_groups: list[dict[str, Any]] = []
    for group in collapsed_groups.values():
        names = sorted({*group["labels"], *group["power"]})
        points = sorted(group["points"])
        normalized_groups.append(
            {
                "names": names,
                "points": points,
                "pins": sorted(
                    group["pins"],
                    key=lambda item: (item["reference"], item["pin"]),
                ),
                "no_connect": bool(
                    group.get("no_connect") or any(point in no_connect_points for point in points)
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


def wire_block(
    x1: float, y1: float, x2: float, y2: float, kind: str = "wire", uuid_str: str | None = None
) -> str:
    """Create a schematic wire or bus block."""
    uid = uuid_str if uuid_str is not None else new_uuid()
    return (
        f"\t({kind}\n"
        f"\t\t(pts (xy {_fmt_mm(x1)} {_fmt_mm(y1)}) (xy {_fmt_mm(x2)} {_fmt_mm(y2)}))\n"
        "\t\t(stroke (width 0) (type solid))\n"
        f'\t\t(uuid "{uid}")\n'
        "\t)"
    )


# Global/hierarchical labels carry a directional icon glyph at their anchor.
# KiCad's GUI writes an explicit (justify ...) away from that icon whenever one
# of these is placed; a file that omits it renders center-justified text on
# top of the icon (issue #373). Mirrors this codebase's own outward-stub
# convention (see _terminal_rotation_from_vector): rotation 0/180 are
# horizontal, so the text needs a horizontal justify away from the icon,
# while 90/270 are vertical and need a vertical one. Verified against a real
# kicad-cli render for each cardinal rotation.
_LABEL_JUSTIFY_BY_ROTATION: dict[int, str] = {0: "left", 90: "bottom", 180: "right", 270: "top"}


def _normalize_label_justify(justify: str | None) -> str | None:
    """Turn a ``LabelJustify`` value into the raw S-expression token string.

    Returns ``None`` when unset (caller may apply a rotation-derived default),
    or ``""`` when the literal ``"none"`` explicitly requests KiCad's centered
    default with no override.
    """
    if justify is None:
        return None
    if justify == "none":
        return ""
    return justify


def label_block(
    name: str,
    x: float,
    y: float,
    rotation: int = 0,
    global_label: bool = False,
    shape: str | None = None,
    kind: str | None = None,
    justify: str | None = None,
) -> str:
    """Create a schematic label block."""
    effective_kind = kind or ("global_label" if global_label else "label")
    effective_shape = shape
    if effective_kind == "global_label" and effective_shape is None:
        effective_shape = "bidirectional"
    shape_line = f"\t\t(shape {effective_shape})\n" if effective_shape else ""
    resolved_justify = _normalize_label_justify(justify)
    if resolved_justify is None:
        resolved_justify = (
            _LABEL_JUSTIFY_BY_ROTATION.get(rotation, "")
            if effective_kind in ("global_label", "hierarchical_label")
            else ""
        )
    justify_part = f" (justify {resolved_justify})" if resolved_justify else ""
    return (
        f"\t({effective_kind} {_sexpr_string(name)}\n"
        f"{shape_line}"
        f"\t\t(at {_fmt_mm(x)} {_fmt_mm(y)} {rotation})\n"
        f"\t\t(effects (font (size 1.524 1.524)){justify_part})\n"
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
    properties: dict[str, str] | None = None,
) -> str:
    """Build a schematic symbol instance block.

    ``properties`` are extra fields written verbatim as additional
    ``(property ...)`` entries. Keys colliding with the standard
    Reference/Value/Footprint/Datasheet fields are ignored so the dedicated
    ``reference``/``value``/``footprint`` inputs always take precedence.
    """
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
    extra_property_blocks: list[str] = []
    for field_name, field_value in (properties or {}).items():
        if field_name in STANDARD_SYMBOL_FIELDS:
            continue
        extra_property_blocks.append(
            f"\t\t(property {_sexpr_string(field_name)} {_sexpr_string(field_value)}\n"
            f"\t\t\t(at {_fmt_mm(x)} {_fmt_mm(y)} 0)\n"
            "\t\t\t(effects (font (size 1.27 1.27)) (hide yes))\n"
            "\t\t)\n"
        )
    extra_properties = "".join(extra_property_blocks)
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
        f"{extra_properties}"
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


def _duplicate_uuids(content: str) -> set[str]:
    """Return element UUIDs that appear more than once in a schematic.

    Every KiCad schematic element carries a unique UUID. A regex/string mutation
    that clones a block (instead of generating a fresh UUID) produces duplicates
    that parse fine but corrupt connectivity and instance paths in KiCad — exactly
    the silent-corruption class the transactional writer must refuse.
    """
    seen: set[str] = set()
    duplicates: set[str] = set()
    for match in re.finditer(r'\(uuid\s+"([0-9a-fA-F-]+)"', content):
        value = match.group(1)
        if value in seen:
            duplicates.add(value)
        else:
            seen.add(value)
    return duplicates


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
    if re.search(r'\(paper\s+"User"\s*\)', content):
        raise ValueError(
            'Refusing to write an invalid schematic with incomplete (paper "User") dimensions.'
        )
    duplicate_uuids = _duplicate_uuids(content)
    if duplicate_uuids:
        sample = ", ".join(sorted(duplicate_uuids)[:5])
        raise ValueError(
            "Refusing to write a schematic with duplicate element UUIDs "
            f"(a string/regex mutation likely cloned a block): {sample}."
        )


def _guard_schematic_structural_loss(
    sch_file: Path,
    before: str,
    after: str,
    *,
    allow_node_loss: bool = False,
) -> None:
    """Refuse accidental structural loss before committing a schematic write.

    Most file-backed schematic tools still apply deterministic text mutations rather
    than a fully lossless kicad-sch-api serializer.  The same round-trip safety
    invariant still applies: a mutator may add or move structure, but it must not
    silently drop fragile constructs such as global labels, hierarchical labels,
    buses, sheets, power symbols, or wires.  Intentional delete/replace workflows
    must opt in with ``allow_node_loss=True`` so destructive behavior is explicit at
    the call site.
    """
    if allow_node_loss or before == after:
        return
    lost = dropped_nodes(before, after)
    if not lost:
        return
    detail = ", ".join(f"{kind} {b}->{a}" for kind, (b, a) in sorted(lost.items()))
    raise SchematicWriteUnsafeError(
        f"Refusing to write {sch_file.name}: the schematic mutation dropped structure "
        f"({detail}). The original file was preserved; use an explicit destructive "
        "path only for intentional delete/replace operations."
    )


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


def _transactional_write_to_schematic_file(
    sch_file: Path,
    mutator: Callable[[str], str],
    *,
    allow_node_loss: bool = False,
) -> str:
    """Read, mutate, validate, and atomically rewrite a schematic file.

    File-backed schematic tools are often invoked in batches.  Keep the full
    read-mutate-validate-replace critical section serialized so concurrent
    calls cannot read the same baseline and lose each other's edits.
    """
    with _SCHEMATIC_WRITE_LOCK:
        sch_file = sch_file.resolve()
        current = sch_file.read_text(encoding="utf-8")
        updated = _normalize_schematic_wire_connectivity(mutator(current))
        _validate_schematic_text(updated)
        _guard_schematic_structural_loss(
            sch_file, current, updated, allow_node_loss=allow_node_loss
        )
        with NamedTemporaryFile("w", encoding="utf-8", delete=False, dir=sch_file.parent) as handle:
            handle.write(updated)
            temp_path = Path(handle.name)
        temp_path.replace(sch_file)
        if updated != current:
            try:
                _record_schematic_visual_diff(sch_file, current, updated)
            except (OSError, ValueError, json.JSONDecodeError, AttributeError) as exc:
                logger.warning(
                    "schematic_visual_diff_record_failed",
                    path=str(sch_file),
                    error=str(exc),
                )
        clear_ttl_cache()
        return str(sch_file)


def _transactional_write_to_schematic(
    mutator: Callable[[str], str],
    *,
    allow_node_loss: bool = False,
) -> str:
    """Read, mutate, validate, and atomically rewrite the active schematic."""
    return _transactional_write_to_schematic_file(
        _get_schematic_file(), mutator, allow_node_loss=allow_node_loss
    )


def transactional_write(
    mutator: Callable[[str], str],
    sch_file: Path | None = None,
    *,
    allow_node_loss: bool = False,
) -> str:
    """Read, mutate, validate, and atomically rewrite a schematic file."""
    if sch_file is not None:
        return _transactional_write_to_schematic_file(
            sch_file, mutator, allow_node_loss=allow_node_loss
        )
    if allow_node_loss:
        return _transactional_write_to_schematic(mutator, allow_node_loss=True)
    return get_schematic_backend().transactional_write(mutator)


def _update_symbol_property_block(
    block: str,
    parsed: dict[str, Any],
    field: str,
    value: str,
) -> str:
    """Set ``field`` to ``value`` on a single placed-symbol block.

    Updates the property in place when present, otherwise inserts a new hidden
    property entry so the value is recorded without disturbing the layout.
    """
    pattern = re.compile(
        rf'(\(property\s+"{re.escape(field)}"\s+")([^"]*)(")',
        re.DOTALL,
    )
    if pattern.search(block):
        escaped_value = _escape_sexpr_string(value)
        return pattern.sub(
            lambda match: f"{match.group(1)}{escaped_value}{match.group(3)}",
            block,
            count=1,
        )

    insert_point = block.rfind("\t\t(instances")
    if insert_point == -1:
        insert_point = block.rfind("\n\t)")
    if insert_point == -1:
        reference = str(parsed.get("reference", "?"))
        raise ValueError(f"Could not update '{reference}' in the schematic.")
    x = parsed["x"]
    y = parsed["y"]
    rotation = parsed["rotation"]
    property_block = (
        f"\t\t(property {_sexpr_string(field)} {_sexpr_string(value)}\n"
        f"\t\t\t(at {_fmt_mm(x)} {_fmt_mm(y)} {rotation})\n"
        "\t\t\t(effects (font (size 1.27 1.27)) (hide yes))\n"
        "\t\t)\n"
    )
    return block[:insert_point] + property_block + block[insert_point:]


def _set_property_position(block: str, field: str, x: float, y: float, angle: float) -> str:
    """Rewrite the ``(at x y angle)`` of a named property inside a symbol block.

    Returns the block unchanged when the property (or its ``at``) is absent, so
    callers can apply this defensively. Only the property's own ``at`` is touched
    — the symbol's placement ``at`` and any nested effects are left intact.
    """
    marker = f'(property "{field}"'
    idx = block.find(marker)
    if idx < 0:
        return block
    prop_block, length = _extract_block(block, idx)
    if not prop_block:
        return block
    at_pattern = re.compile(r"\(at\s+[-\d.]+\s+[-\d.]+\s+[-\d.]+\)")
    if at_pattern.search(prop_block) is None:
        return block
    new_at = f"(at {_fmt_mm(x)} {_fmt_mm(y)} {int(round(angle))})"
    new_prop = at_pattern.sub(new_at, prop_block, count=1)
    return block[:idx] + new_prop + block[idx + length :]


def _symbol_body_and_pins(parsed: dict[str, Any]) -> tuple[GeoBox, list[tuple[float, float]]]:
    """Return the body box and absolute pin tips for a parsed placed symbol."""
    x = float(parsed.get("x", 0.0) or 0.0)
    y = float(parsed.get("y", 0.0) or 0.0)
    pin_points: list[tuple[float, float]] = []
    lib_id = str(parsed.get("lib_id", "") or "")
    if lib_id:
        try:
            library, symbol_name = _split_lib_id(lib_id)
            pins = get_pin_positions(
                library=library,
                symbol_name=symbol_name,
                sym_x=x,
                sym_y=y,
                rotation=int(parsed.get("rotation", 0) or 0),
                unit=int(parsed.get("unit", 1) or 1),
            )
            pin_points = list(pins.values())
        except (FileNotFoundError, OSError, ValueError) as exc:
            logger.debug("autoplace_fields_pin_lookup_failed", lib_id=lib_id, error=str(exc))
    body = body_box_from_pins(pin_points, center=(x, y))
    return body, pin_points


def _build_autoplace_fields_mutator(
    sch_file: Path,
    references: list[str] | None = None,
) -> tuple[Callable[[str], str], list[str], list[str]]:
    """Return ``(mutator, targets, updated)`` for Reference/Value field placement.

    ``mutator`` rewrites each target symbol's visible field positions; ``updated``
    is appended to as the mutator runs so callers can report what changed. Shared
    by the ``sch_autoplace_fields`` tool and the readability fix loop.
    """
    symbols = parse_schematic_file(sch_file)["symbols"]
    wanted = set(references) if references else None

    bodies: dict[str, GeoBox] = {}
    body_pins: dict[str, tuple[GeoBox, list[tuple[float, float]]]] = {}
    for symbol in symbols:
        ref = str(symbol.get("reference", ""))
        if not ref:
            continue
        body, pins = _symbol_body_and_pins(symbol)
        bodies[ref] = body
        body_pins[ref] = (body, pins)

    targets = [
        str(s.get("reference", ""))
        for s in symbols
        if str(s.get("reference", "")) and (wanted is None or str(s.get("reference", "")) in wanted)
    ]
    updated: list[str] = []

    def mutator(content: str) -> str:
        new_content = content
        for ref in targets:
            match = _find_placed_symbol_block(new_content, ref)
            if match is None:
                continue
            block, start, end, parsed = match
            body, pins = body_pins.get(ref, _symbol_body_and_pins(parsed))
            obstacles = [b for other, b in bodies.items() if other != ref]
            specs = [
                FieldSpec("Reference", str(parsed.get("reference", ""))),
                FieldSpec("Value", str(parsed.get("value", ""))),
            ]
            placements = autoplace_fields(body, pins, obstacles, specs)
            new_block = block
            for spec, placement in zip(specs, placements, strict=True):
                if not spec.text:
                    continue
                new_block = _set_property_position(
                    new_block, spec.name, placement.x, placement.y, placement.angle
                )
            if new_block != block:
                new_content = new_content[:start] + new_block + new_content[end:]
                updated.append(ref)
        return new_content

    return mutator, targets, updated


def _autoplace_fields_apply(sch_file: Path, references: list[str] | None = None) -> list[str]:
    """Apply Reference/Value field auto-placement to ``sch_file`` and return moved refs."""
    mutator, targets, updated = _build_autoplace_fields_mutator(sch_file, references)
    if not targets:
        return []
    _transactional_write_to_schematic_file(sch_file, mutator)
    return updated


def _resize_sheet_apply(sch_file: Path, paper: str) -> bool:
    """Set the sheet paper size on ``sch_file``; return whether it changed."""
    if paper not in PAPER_SIZES_MM:
        return False
    changed = False

    def mutator(current: str) -> str:
        nonlocal changed
        new_text = re.sub(
            r'\(paper\s+"[^"]+"(?:\s+[\d.]+\s+[\d.]+)?\)',
            f'(paper "{paper}")',
            current,
            count=1,
        )
        if new_text == current and "(paper" not in current:
            new_text = re.sub(
                r"(\(kicad_sch[^\n]*\n)",
                rf'\1\t(paper "{paper}")\n',
                current,
                count=1,
            )
        changed = new_text != current
        return new_text

    _transactional_write_to_schematic_file(sch_file, mutator)
    return changed


def _schematic_has_connections(content: str) -> bool:
    """Whether the sheet has any geometry/name connections symbols attach to.

    Wires, labels (local/global/hierarchical) and power symbols all pin a
    symbol's pins to a net by position; moving such a symbol would silently break
    those connections. When none are present the sheet is a bag of unconnected
    symbols that can be re-spaced freely.
    """
    if _extract_wires(content) or _extract_labels(content):
        return True
    if re.search(r"\(bus\b", content):
        return True
    # Power symbols (lib_id "power:...") connect pins by name at their position.
    return bool(re.search(r'\(lib_id\s+"power:', content))


def _shift_at_in_block(block: str, dx: float, dy: float) -> str:
    """Translate every ``(at x y r)`` in a symbol instance block by (dx, dy).

    A placed symbol's root and property positions are all absolute schematic
    coordinates, so shifting them together moves the symbol and its text as a
    unit. Pins carry no ``(at)`` in the instance (they live in lib_symbols), so
    this never disturbs electrical geometry.
    """

    def repl(match: re.Match[str]) -> str:
        x = float(match.group(1)) + dx
        y = float(match.group(2)) + dy
        rot = match.group(3)
        return f"(at {_fmt_mm(x)} {_fmt_mm(y)} {rot})"

    return re.sub(r"\(at\s+(-?[\d.]+)\s+(-?[\d.]+)\s+(-?[\d.]+)\)", repl, block)


def _respace_symbols_apply(sch_file: Path) -> list[str]:
    """Re-space all symbols onto a body-sized, page-bounded grid; return moved refs.

    Caller must ensure the sheet has no connections (see
    :func:`_schematic_has_connections`) — this moves symbols freely and is only
    safe when nothing attaches to their pins. Cell size is the largest symbol
    body plus clearance so even wide parts do not overlap after the move.
    """
    symbols = parse_schematic_file(sch_file)["symbols"]
    if len(symbols) < 2:
        return []

    max_w = 0.0
    max_h = 0.0
    old_pos: dict[str, tuple[float, float]] = {}
    for symbol in symbols:
        ref = str(symbol.get("reference", ""))
        if not ref:
            continue
        body, _pins = _symbol_body_and_pins(symbol)
        max_w = max(max_w, body.width)
        max_h = max(max_h, body.height)
        old_pos[ref] = (float(symbol.get("x", 0.0) or 0.0), float(symbol.get("y", 0.0) or 0.0))

    # Cell adds clearance plus room for the Reference/Value text band below a part.
    def _grid_ceil(value: float) -> float:
        return math.ceil(value / SCHEMATIC_GRID_MM) * SCHEMATIC_GRID_MM

    cell_w = max(AUTO_LAYOUT_COLUMN_SPACING_MM, _grid_ceil(max_w + 5.08))
    cell_h = max(AUTO_LAYOUT_ROW_SPACING_MM, _grid_ceil(max_h + 7.62))
    cols = max(1, math.ceil(math.sqrt(len(old_pos))))
    paper = select_paper_for_capacity(
        math.ceil(len(old_pos) / cols) + 1, cell_w=cell_w, cell_h=cell_h
    )
    max_cols = min(cols, _sheet_usable_cols(paper, cell_w))

    occupied: set[tuple[int, int]] = set()
    new_pos: dict[str, tuple[float, float]] = {}
    for ref in sorted(old_pos):
        new_pos[ref] = _next_free_cell(
            occupied, cell_w=cell_w, cell_h=cell_h, max_cols=max_cols, paper=paper
        )

    moved: list[str] = []

    def mutator(content: str) -> str:
        new_content = content
        for ref in sorted(new_pos):
            match = _find_placed_symbol_block(new_content, ref)
            if match is None:
                continue
            block, start, end, _parsed = match
            ox, oy = old_pos[ref]
            nx, ny = new_pos[ref]
            dx, dy = nx - ox, ny - oy
            if abs(dx) < 1e-6 and abs(dy) < 1e-6:
                continue
            new_block = _shift_at_in_block(block, dx, dy)
            new_content = new_content[:start] + new_block + new_content[end:]
            moved.append(ref)
        return new_content

    if not new_pos:
        return []
    _transactional_write_to_schematic_file(sch_file, mutator)
    return moved


def _update_symbol_property_text_fallback(reference: str, field: str, value: str) -> str:
    """Update a symbol property in the active schematic."""
    payload = UpdatePropertiesInput(reference=reference, field=field, value=value)

    updated_count = 0

    def mutator(current: str) -> str:
        nonlocal updated_count
        matches = _find_placed_symbol_blocks(current, payload.reference)
        if not matches:
            raise ValueError(f"Reference '{payload.reference}' was not found in the schematic.")
        updated_count = len(matches)

        updated = current
        for block, start, end, parsed in reversed(matches):
            new_block = _update_symbol_property_block(block, parsed, payload.field, payload.value)
            updated = updated[:start] + new_block + updated[end:]
        return updated

    _transactional_write_to_schematic(mutator)
    return f"Updated {payload.reference}.{payload.field} on {updated_count} instance(s)."


def update_symbol_property(reference: str, field: str, value: str) -> str:
    """Update a symbol property through the active backend adapter."""
    return get_schematic_backend().update_symbol_property(reference, field, value)


def _set_symbol_dnp_text_fallback(
    reference: str,
    enabled: bool,
    reason: str | None = None,
) -> str:
    """Set KiCad's native placed-symbol DNP flag in the active schematic.

    When ``reason`` is provided it is recorded in the ``DNP Reason`` property so
    later reads (``sch_get_population_status``) and variant BOMs can surface why
    a part is unpopulated.
    """
    native_value = "yes" if enabled else "no"
    updated_count = 0

    def _set_dnp_flag(block: str) -> str:
        dnp_pattern = re.compile(r"(\n\s*\(dnp\s+)(yes|no)(\)?)")
        if dnp_pattern.search(block):
            return dnp_pattern.sub(
                lambda match: f"{match.group(1)}{native_value}{match.group(3)}",
                block,
                count=1,
            )

        insert_match = re.search(r"\n\s*\(on_board\s+(?:yes|no)\)", block)
        if insert_match is not None:
            return (
                block[: insert_match.end()]
                + f"\n\t\t(dnp {native_value})"
                + block[insert_match.end() :]
            )

        insert_point = block.rfind("\t\t(instances")
        if insert_point == -1:
            insert_point = block.rfind("\n\t)")
        if insert_point == -1:
            raise ValueError(f"Could not update native DNP on '{reference}' in the schematic.")
        return block[:insert_point] + f"\t\t(dnp {native_value})\n" + block[insert_point:]

    def mutator(current: str) -> str:
        nonlocal updated_count
        matches = _find_placed_symbol_blocks(current, reference)
        if not matches:
            raise ValueError(f"Reference '{reference}' was not found in the schematic.")
        updated_count = len(matches)
        updated = current
        for block, start, end, parsed in reversed(matches):
            new_block = _set_dnp_flag(block)
            if reason is not None:
                new_block = _update_symbol_property_block(
                    new_block, parsed, DNP_REASON_PROPERTY, reason
                )
            updated = updated[:start] + new_block + updated[end:]
        return updated

    _transactional_write_to_schematic(mutator)
    state = "DNP" if enabled else "Populate"
    return f"Set {reference} native population state to {state} on {updated_count} instance(s)."


def set_symbol_dnp(reference: str, enabled: bool, reason: str | None = None) -> str:
    """Set KiCad's native DNP flag on a placed schematic symbol."""
    return _set_symbol_dnp_text_fallback(reference, enabled, reason)


def _find_all_placed_symbol_blocks(
    content: str,
) -> list[tuple[str, int, int, dict[str, Any]]]:
    """Return every placed ``(symbol ...)`` block with its parsed metadata."""
    matches: list[tuple[str, int, int, dict[str, Any]]] = []
    cursor = 0
    while cursor < len(content):
        if content[cursor:].startswith("(symbol"):
            block, length = _extract_block(content, cursor)
            if block:
                parsed = _parse_symbol_block(block)
                if parsed is not None:
                    matches.append((block, cursor, cursor + length, parsed))
                cursor += length
                continue
        cursor += 1
    return matches


def _sheet_name_matches(path: Path, sheet: str | None) -> bool:
    """True when ``sheet`` is unset or names this schematic file."""
    if sheet is None or not sheet.strip():
        return True
    requested = sheet.strip().casefold()
    return requested in {path.name.casefold(), path.stem.casefold(), str(path).casefold()}


def _population_record_from_symbol(
    *,
    sch_file: Path,
    block: str,
    parsed: dict[str, Any],
) -> dict[str, Any]:
    """Build a population-status record for one placed symbol."""
    properties = _symbol_property_values(block)
    dnp = _symbol_bool_flag(block, "dnp", default=bool(parsed.get("dnp", False)))
    in_bom = _symbol_bool_flag(block, "in_bom", default=bool(parsed.get("in_bom", True)))
    return {
        "reference": str(parsed.get("reference", "")),
        "value": str(parsed.get("value", "")),
        "footprint": str(parsed.get("footprint", "")),
        "sheet": sch_file.stem,
        "sheet_file": str(sch_file),
        "populated": not dnp,
        "dnp": dnp,
        "in_bom": in_bom,
        "reason": properties.get(DNP_REASON_PROPERTY, ""),
    }


def native_population_flags(sch_file: Path) -> dict[str, dict[str, bool]]:
    """Return ``{reference: {"dnp": ..., "in_bom": ...}}`` for one schematic file.

    Reads the native ``(dnp ...)`` / ``(in_bom ...)`` toggles straight from the
    file so callers get the authoritative state even when the active backend
    does not model the DNP flag.
    """
    flags: dict[str, dict[str, bool]] = {}
    try:
        content = sch_file.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return flags
    for block, _start, _end, parsed in _find_all_placed_symbol_blocks(content):
        reference = str(parsed.get("reference", ""))
        if not reference or reference.startswith("#"):
            continue
        flags[reference] = {
            "dnp": _symbol_bool_flag(block, "dnp", default=False),
            "in_bom": _symbol_bool_flag(block, "in_bom", default=True),
        }
    return flags


def _population_records(
    reference: str | None = None,
    sheet: str | None = None,
) -> list[dict[str, Any]]:
    """Collect native Populate/DNP records across the project's schematics."""
    target_ref = reference.strip() if reference else ""
    records: list[dict[str, Any]] = []
    for sch_file in project_schematic_files():
        if not _sheet_name_matches(sch_file, sheet):
            continue
        try:
            content = sch_file.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        matches = (
            _find_placed_symbol_blocks(content, target_ref)
            if target_ref
            else _find_all_placed_symbol_blocks(content)
        )
        for block, _start, _end, parsed in matches:
            reference_name = str(parsed.get("reference", ""))
            if reference_name.startswith("#"):
                # Skip power/hidden pseudo-symbols (e.g. #PWR, #FLG).
                continue
            records.append(
                _population_record_from_symbol(sch_file=sch_file, block=block, parsed=parsed)
            )
    return records


def _parse_wire_block(block: str) -> dict[str, Any] | None:
    pts_match = re.search(
        (r"\(pts\s+\(xy\s+([-\d.]+)\s+([-\d.]+)\)\s+" r"\(xy\s+([-\d.]+)\s+([-\d.]+)\)\s*\)"),
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
        return f"{match.group(1)}{_fmt_mm(shifted_x)} {_fmt_mm(shifted_y)}{match.group(4)}"

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
        return (
            "The schematic was updated and a best-effort KiCad GUI reload request was sent. "
            "Schematic disk reload in the open GUI document is not confirmed."
        )
    except Exception as exc:
        logger.debug("schematic_reload_failed", error=str(exc))
        return "The schematic was updated. Reload it manually in KiCad if needed."


def _reload_schematic() -> str:
    """Reload the schematic through the active backend adapter."""
    return get_schematic_backend().reload_schematic()


def _template_yaml_loader_factory() -> Callable[[TextIO], Any]:
    """Return PyYAML's safe loader without importing it during server startup."""
    import yaml

    return yaml.safe_load


def _parse_semantic_ir(schematic_file: Path) -> CircuitLike:
    """Parse semantic IR lazily to avoid the existing compatibility import cycle."""
    from ..ir import parse_schematic_to_ir

    return cast(CircuitLike, parse_schematic_to_ir(schematic_file, load_pin_metadata=True))


def _lint_semantic_ir(circuit: CircuitLike) -> Iterable[FindingLike]:
    """Run semantic IR lint lazily to avoid importing IR during server startup."""
    from ..ir import IRCircuit, lint_circuit

    return cast(Iterable[FindingLike], lint_circuit(cast(IRCircuit, circuit)))


def _prepare_circuit_compilation_inputs(
    *,
    symbols: list[dict[str, Any]] | None = None,
    wires: list[dict[str, Any]] | None = None,
    labels: list[dict[str, Any]] | None = None,
    power_symbols: list[dict[str, Any]] | None = None,
    nets: list[dict[str, Any]] | None = None,
    snap_to_grid: bool = True,
    auto_layout: bool = False,
    unsafe_routed_wires: bool = False,
    paper: str = "A4",
    max_paper: str = "A3",
) -> PreparedCircuitInputs:
    prepared = _prepare_build_circuit_inputs(
        symbols=symbols,
        wires=wires,
        labels=labels,
        power_symbols=power_symbols,
        nets=nets,
        snap_to_grid=snap_to_grid,
        auto_layout=auto_layout,
        unsafe_routed_wires=unsafe_routed_wires,
        paper=paper,
        max_paper=max_paper,
    )
    return PreparedCircuitInputs(
        symbols=prepared[0],
        powers=prepared[1],
        labels=prepared[2],
        wires=prepared[3],
        nets=prepared[4],
        generated_wires=prepared[5],
        unresolved_nets=prepared[6],
        resolution_stats=prepared[7],
        chosen_paper=prepared[8],
    )


def _write_compiled_schematic(content: str, path: Path, allow_node_loss: bool) -> None:
    transactional_write(
        lambda _current: content,
        path,
        allow_node_loss=allow_node_loss,
    )


def _count_schematic_nodes(content: str) -> tuple[int, int]:
    """Return ``(symbol_count, label_count)`` for placed nodes in ``content``.

    Only top-level placed ``(symbol ...)`` instances are counted (library symbol
    definitions inside ``(lib_symbols ...)`` are ignored), alongside every
    ``label`` / ``global_label`` / ``hierarchical_label``.
    """
    symbol_count = len(_find_all_placed_symbol_blocks(content))
    label_count = len(re.findall(r"\((?:label|global_label|hierarchical_label)\b", content))
    return symbol_count, label_count


def _snapshot_sheet_before_replace(sch_file: Path) -> tuple[int, int, Path | None]:
    """Count existing nodes and back up ``sch_file`` before a destructive rebuild.

    Returns ``(symbol_count, label_count, backup_path)``. When the sheet is absent
    or empty (no placed symbols or labels) no backup is written and ``backup_path``
    is ``None``, so callers never claim a spurious backup for empty sheets.
    """
    resolved_file = sch_file.resolve()
    if not resolved_file.is_file():
        return 0, 0, None
    content = resolved_file.read_text(encoding="utf-8")
    symbol_count, label_count = _count_schematic_nodes(content)
    if symbol_count == 0 and label_count == 0:
        return symbol_count, label_count, None
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    nonce = time.time_ns()
    parent_dir = resolved_file.parent.resolve()
    backup_path = (parent_dir / f"{resolved_file.name}.{timestamp}.{nonce}.bak").resolve()
    if parent_dir not in backup_path.parents and backup_path.parent != parent_dir:
        raise ValueError(f"Unsafe backup path: {backup_path}")
    backup_path.write_text(content, encoding="utf-8")
    return symbol_count, label_count, backup_path


def _active_project_name() -> str:
    config = get_config()
    return config.project_file.stem if config.project_file is not None else "KiCadMCP"


def _load_layout_schematic(path: Path) -> SchematicLike:
    return cast(SchematicLike, _load_kicad_schematic(path))


def _load_layout_design_intent() -> FunctionalDesignIntentLike:
    from .project import load_design_intent

    return load_design_intent()


def _connectivity_symbol_bboxes(content: str) -> list[BoundingBoxLike]:
    return cast(list[BoundingBoxLike], _get_symbol_bboxes(content))


def _connectivity_route_avoiding_obstacles(
    start: tuple[float, float],
    end: tuple[float, float],
    obstacles: list[BoundingBoxLike],
    snap_to_grid: bool,
) -> tuple[list[tuple[float, float, float, float]], str | None]:
    return _route_avoiding_obstacles(
        start,
        end,
        cast(list[BBox], obstacles),
        snap_to_grid,
    )


def _connectivity_target_detail(target: SchematicTargetLike) -> str:
    return _format_target_detail(cast(_SchematicTarget, target))


def _connectivity_transactional_write(
    mutator: Callable[[str], str],
    path: Path | None,
) -> str:
    return transactional_write(mutator, path)


def _register_inspection_and_analysis(mcp: FastMCP) -> None:
    """Register schematic inspection, compilation, rendering, and topology tools."""
    inspection_service = SchematicInspectionService(
        parse_schematic=parse_schematic_file,
        with_diagnostics=_with_schematic_diagnostics,
        population_records=_population_records,
        symbol_available_units=get_symbol_available_units,
        pin_positions_lookup=get_pin_positions,
    )
    schematic_inspection.register(
        mcp,
        schematic_inspection.SchematicInspectionDependencies(
            resolve_target=_resolve_schematic_target,
            active_schematic_file=_get_schematic_file,
            service=inspection_service,
        ),
    )

    layout_inspection_service = SchematicLayoutInspectionService(
        active_schematic_file=_get_schematic_file,
        parse_schematic=parse_schematic_file,
        with_diagnostics=_with_schematic_diagnostics,
        symbol_bbox_bounds=_symbol_bbox_bounds,
        estimate_occupied_cells=_estimate_occupied_cells,
        keepout_occupied_cells=_keepout_occupied_cells,
        next_free_cell=_next_free_cell,
    )
    schematic_layout_inspection.register(
        mcp,
        schematic_layout_inspection.SchematicLayoutInspectionDependencies(
            service=layout_inspection_service,
        ),
    )

    document_settings_service = SchematicDocumentSettingsService(
        active_schematic_file=_get_schematic_file,
        resolve_target=_resolve_schematic_target,
        parse_schematic=parse_schematic_file,
        apply_title_block_updates=_apply_title_block_updates,
        transactional_write=transactional_write,
        reload_schematic=_reload_schematic,
        format_target_detail=_format_target_detail,
        read_sheet_paper=_read_sheet_paper,
        sheet_usable_cols=_sheet_usable_cols,
        sheet_usable_rows=_sheet_usable_rows,
        paper_sizes_mm=PAPER_SIZES_MM,
        layout_origin_x_mm=AUTO_LAYOUT_ORIGIN_X_MM,
        sheet_margin_mm=_SHEET_MARGIN_MM,
        symbol_half_width_mm=_SYMBOL_HALF_W_MM,
        symbol_half_height_mm=_SYMBOL_HALF_H_MM,
    )
    schematic_document_settings.register(
        mcp,
        schematic_document_settings.SchematicDocumentSettingsDependencies(
            service=document_settings_service,
        ),
    )

    template_catalog_service = SchematicTemplateCatalogService(
        templates_dir=Path(__file__).parent.parent / "templates" / "subcircuits",
        yaml_loader_factory=_template_yaml_loader_factory,
    )
    schematic_template_catalog.register(
        mcp,
        schematic_template_catalog.SchematicTemplateCatalogDependencies(
            service=template_catalog_service,
        ),
    )

    template_instantiation_service = SchematicTemplateInstantiationService(
        templates_dir=Path(__file__).parent.parent / "templates" / "subcircuits",
        yaml_loader_factory=_template_yaml_loader_factory,
    )
    schematic_template_instantiation.register(
        mcp,
        schematic_template_instantiation.SchematicTemplateInstantiationDependencies(
            service=template_instantiation_service,
        ),
    )

    semantic_ir_service = SchematicSemanticIRService(
        active_schematic_file=_get_schematic_file,
        parse_circuit=_parse_semantic_ir,
        lint_circuit=_lint_semantic_ir,
        with_diagnostics=_with_schematic_diagnostics,
        warn_parse_failure=lambda exc: logger.warning(
            "sch_get_circuit_ir parse failed", error=str(exc)
        ),
    )
    schematic_semantic_ir.register(
        mcp,
        schematic_semantic_ir.SchematicSemanticIRDependencies(
            service=semantic_ir_service,
        ),
    )

    circuit_compilation_service = SchematicCircuitCompilationService(
        active_schematic_file=lambda: _get_schematic_file(),
        project_name=_active_project_name,
        snapshot_before_replace=_snapshot_sheet_before_replace,
        read_sheet_paper=lambda path: _read_sheet_paper(path),
        read_sheet_paper_declaration=lambda path: _read_sheet_paper_declaration(path),
        prepare_inputs=_prepare_circuit_compilation_inputs,
        render_report=lambda **kwargs: _render_net_compilation_report(**kwargs),
        paper_sizes=PAPER_SIZES_MM,
        new_uuid=lambda: new_uuid(),
        load_lib_symbol=lambda library, symbol_name: load_lib_symbol(library, symbol_name),
        snap_point=lambda x, y, enabled: _snap_point(x, y, enabled),
        place_symbol_block=lambda **kwargs: place_symbol_block(**kwargs),
        wire_block=lambda x1, y1, x2, y2: wire_block(x1, y1, x2, y2),
        snap_line=lambda x1, y1, x2, y2, enabled: _snap_line(x1, y1, x2, y2, enabled),
        label_block=lambda name, x, y, rotation, **kwargs: label_block(
            name, x, y, rotation, **kwargs
        ),
        normalize_connectivity=lambda content: _normalize_schematic_wire_connectivity(content),
        validate_schematic_text=lambda content: _validate_schematic_text(content),
        transactional_write=_write_compiled_schematic,
        reload_schematic=lambda: _reload_schematic(),
        warn_unresolved=lambda payload: logger.warning(
            "schematic_netlist_routing_incomplete",
            **payload,
        ),
    )
    schematic_circuit_compilation.register(
        mcp,
        schematic_circuit_compilation.SchematicCircuitCompilationDependencies(
            service=circuit_compilation_service,
        ),
    )

    rendering_service = SchematicRenderingService(
        resolve_target=lambda sheet, sheet_file: _resolve_schematic_target(
            sheet=sheet,
            sheet_file=sheet_file,
        ),
        parse_schematic=lambda path: parse_schematic_file(path),
        has_renderable_content=lambda data: _schematic_has_renderable_content(data),
        safe_output_path=lambda raw_name, default_name: _safe_render_output_path(
            raw_name,
            default_name=default_name,
        ),
        render_png_artifact=lambda schematic_file, output_path, dpi, crop, title: (
            _render_schematic_png_artifact(
                schematic_file,
                output_path,
                dpi=dpi,
                crop_to_content=crop,
                include_title_block=title,
            )
        ),
        load_visual_diff=lambda path: _load_schematic_visual_diff(path),
        render_png_visual_diff=lambda before, after, output: _render_png_visual_diff(
            before,
            after,
            output,
        ),
        preview_files=lambda root, include_children: _schematic_live_preview_files(
            root,
            include_children,
        ),
        preview_signature=lambda paths: _schematic_live_preview_signature(paths),
        preview_state_filename=lambda path, include_children: (
            _schematic_live_preview_state_filename(path, include_children)
        ),
        preview_state_read=lambda filename: _schematic_live_preview_state_read(filename),
        preview_state_write=lambda filename, state: _schematic_live_preview_state_write(
            filename,
            state,
        ),
        preview_changed_files=lambda before, after: _schematic_live_preview_changed_files(
            before,
            after,
        ),
        preview_render_path=lambda target_path, watched_files, changed_files: (
            _schematic_live_preview_render_path(
                target_path=target_path,
                watched_files=watched_files,
                changed_files=changed_files,
            )
        ),
        preview_payload=lambda **kwargs: _schematic_live_preview_payload(**kwargs),
        reload_schematic=lambda: _reload_schematic(),
        now_ns=lambda: time.time_ns(),
    )
    schematic_rendering.register(
        mcp,
        schematic_rendering.SchematicRenderingDependencies(
            service=rendering_service,
        ),
    )

    topology_service = SchematicTopologyService(
        load_schematic=_load_kicad_schematic,
        with_diagnostics=_with_schematic_diagnostics,
        build_connectivity_groups=_build_connectivity_groups,
        iter_child_sheet_paths=_iter_child_sheet_paths,
        parse_schematic=parse_schematic_file,
        warn=logger.warning,
        read_text=lambda path: path.read_text(encoding="utf-8"),
    )
    schematic_topology.register(
        mcp,
        schematic_topology.SchematicTopologyDependencies(
            active_schematic_file=_get_schematic_file,
            service=topology_service,
        ),
    )


def _register_authoring(mcp: FastMCP) -> None:
    """Register schematic mutation and authoring tools."""
    symbol_mutation_service = SchematicSymbolMutationService(
        update_symbol_property=update_symbol_property,
        set_symbol_dnp=set_symbol_dnp,
        reload_schematic=_reload_schematic,
        snap_point=_snap_point,
        snap_notice=_snap_notice,
        transactional_write=transactional_write,
        find_placed_symbol_block=_find_placed_symbol_block,
        shift_symbol_block=_shift_symbol_block,
    )
    schematic_symbol_mutation.register(
        mcp,
        schematic_symbol_mutation.SchematicSymbolMutationDependencies(
            service=symbol_mutation_service,
        ),
    )

    destructive_edit_service = SchematicDestructiveEditService(
        active_schematic_file=_get_schematic_file,
        read_schematic_text=lambda path: path.read_text(encoding="utf-8", errors="ignore"),
        extract_wires=_extract_wires,
        wire_id_matches=_wire_id_matches,
        wire_signature=_wire_signature,
        extract_block=_extract_block,
        parse_wire_block=_parse_wire_block,
        format_mm=_fmt_mm,
        transactional_write=transactional_write,
        reload_schematic=_reload_schematic,
        find_placed_symbol_blocks=_find_placed_symbol_blocks,
        symbol_connection_points=_symbol_connection_points,
        parse_symbol_block=_parse_symbol_block,
        coordinate_key=_coord_pair_key,
        parse_label_block=_parse_label_block,
        parse_no_connect_block=_parse_no_connect_block,
        snap_point=_snap_point,
        snap_notice=_snap_notice,
        normalize_label_justify=_normalize_label_justify,
        set_label_justify=_set_label_justify,
    )
    schematic_destructive_edit.register(
        mcp,
        schematic_destructive_edit.SchematicDestructiveEditDependencies(
            service=destructive_edit_service,
        ),
    )

    basic_authoring_service = SchematicBasicAuthoringService(
        resolve_target=_resolve_schematic_target,
        parse_schematic=parse_schematic_file,
        project_name=_project_name,
        load_lib_symbol=load_lib_symbol,
        suggest_symbol_names=suggest_symbol_names,
        symbol_available_units=get_symbol_available_units,
        format_available_units=_format_available_units,
        snap_point=_snap_point,
        snap_line=_snap_line,
        snap_notice=_snap_notice,
        point_near_existing=_point_near_existing,
        validate_footprint=_validate_footprint,
        place_symbol_block=place_symbol_block,
        wire_block=wire_block,
        bus_entry_block=bus_entry_block,
        no_connect_block=no_connect_block,
        label_block=label_block,
        append_before_sheet_instances=_append_before_sheet_instances,
        transactional_write=transactional_write,
        reload_schematic=_reload_schematic,
        new_uuid=new_uuid,
        format_mm=_fmt_mm,
    )
    schematic_basic_authoring.register(
        mcp,
        schematic_basic_authoring.SchematicBasicAuthoringDependencies(
            service=basic_authoring_service,
        ),
    )

    back_annotation_service = SchematicBackAnnotationService(
        project_file=lambda: get_config().project_file,
        symbol_by_reference=_symbol_by_reference,
        split_lib_id=_split_lib_id,
        pin_alias_positions=get_pin_alias_positions,
        symbol_library_file=_symbol_library_file,
        collect_symbol_blocks=_collect_symbol_blocks,
        available_units_from_blocks=_available_units_from_blocks,
        load_state=_load_schematic_state,
        save_state=_save_schematic_state,
    )
    schematic_back_annotation.register(
        mcp,
        schematic_back_annotation.SchematicBackAnnotationDependencies(
            service=back_annotation_service,
        ),
    )

    hierarchy_authoring_service = SchematicHierarchyAuthoringService(
        active_schematic_file=_get_schematic_file,
        resolve_target=_resolve_schematic_target,
        resolve_create_schematic=_resolve_create_schematic,
        load_schematic=_load_hierarchy_schematic,
        snap_point=_snap_point,
        snap_notice=_snap_notice,
        project_name=_project_name,
        default_sheet_size=(DEFAULT_SHEET_WIDTH_MM, DEFAULT_SHEET_HEIGHT_MM),
        label_block=label_block,
        append_before_sheet_instances=_append_before_sheet_instances,
        transactional_write=transactional_write,
        reload_schematic=_reload_schematic,
        warn=logger.warning,
        read_text=lambda path: path.read_text(encoding="utf-8"),
        grid_mm=lambda: SCHEMATIC_GRID_MM,
        new_uuid=new_uuid,
        wire_block=wire_block,
        parse_wire_endpoints=_wire_endpoints,
    )
    schematic_hierarchy_authoring.register(
        mcp,
        schematic_hierarchy_authoring.SchematicHierarchyAuthoringDependencies(
            service=hierarchy_authoring_service,
        ),
    )

    connectivity_authoring_service = SchematicConnectivityAuthoringService(
        resolve_target=lambda sheet, sheet_file: _resolve_schematic_target(
            sheet=sheet,
            sheet_file=sheet_file,
        ),
        parse_schematic=parse_schematic_file,
        project_name=_project_name,
        new_uuid=new_uuid,
        get_pin_positions=get_pin_positions,
        get_pin_alias_positions=get_pin_alias_positions,
        pin_label_stub_direction=_pin_label_stub_direction,
        is_origin_pin_power_symbol=_is_origin_pin_power_symbol,
        is_power_net=_is_power_net,
        load_lib_symbol=load_lib_symbol,
        wire_block=wire_block,
        power_symbol_rotation_from_vector=_power_symbol_rotation_from_vector,
        place_symbol_block=place_symbol_block,
        terminal_rotation_from_vector=_terminal_rotation_from_vector,
        label_block=label_block,
        append_before_sheet_instances=_append_before_sheet_instances,
        transactional_write=_connectivity_transactional_write,
        reload_schematic=_reload_schematic,
        format_target_detail=_connectivity_target_detail,
        active_schematic_file=_get_schematic_file,
        split_lib_id=_split_lib_id,
        get_symbol_bboxes=_connectivity_symbol_bboxes,
        route_avoiding_obstacles=_connectivity_route_avoiding_obstacles,
        run_auto_add_missing_junctions=run_auto_add_missing_junctions,
        snap_tolerance_mm=SNAP_TOLERANCE_MM,
    )
    schematic_connectivity_authoring.register(
        mcp,
        schematic_connectivity_authoring.SchematicConnectivityAuthoringDependencies(
            service=connectivity_authoring_service,
        ),
    )

    lifecycle_authoring_service = SchematicLifecycleAuthoringService(
        snap_point=_snap_point,
        snap_notice=_snap_notice,
        next_reference=_next_reference,
        place_symbol_block=place_symbol_block,
        append_before_sheet_instances=_append_before_sheet_instances,
        transactional_write=transactional_write,
        reload_schematic=_reload_schematic,
        active_schematic_file=_get_schematic_file,
        parse_schematic=parse_schematic_file,
        sort_symbols_for_annotation=_sort_symbols_for_annotation,
    )
    schematic_lifecycle_authoring.register(
        mcp,
        schematic_lifecycle_authoring.SchematicLifecycleAuthoringDependencies(
            service=lifecycle_authoring_service,
        ),
    )

    layout_automation_service = SchematicLayoutAutomationService(
        active_schematic_file=_get_schematic_file,
        load_schematic=_load_layout_schematic,
        parse_schematic=parse_schematic_file,
        with_diagnostics=_with_schematic_diagnostics,
        estimate_occupied_cells=_estimate_occupied_cells,
        next_free_cell=_next_free_cell,
        snap_point=_snap_point,
        reload_schematic=_reload_schematic,
        build_autoplace_fields_mutator=_build_autoplace_fields_mutator,
        transactional_write_to_schematic_file=_transactional_write_to_schematic_file,
        run_visual_qa=_run_visual_qa,
        read_sheet_paper=_read_sheet_paper,
        paper_ladder=_PAPER_LADDER,
        resize_sheet_apply=_resize_sheet_apply,
        schematic_has_connections=_schematic_has_connections,
        respace_symbols_apply=_respace_symbols_apply,
        autoplace_fields_apply=_autoplace_fields_apply,
        load_design_intent=_load_layout_design_intent,
        normalize_anchor_refs=_normalize_anchor_refs,
        sheet_usable_cols=_sheet_usable_cols,
        sheet_usable_rows=_sheet_usable_rows,
        paper_sizes_mm=PAPER_SIZES_MM,
        classify_symbol=_classify_symbol,
        functional_zone_origin=_functional_zone_origin,
        functional_zones=tuple(_FUNCTIONAL_ZONES),
        zone_max_cols=_ZONE_MAX_COLS,
        auto_layout_origin_x_mm=AUTO_LAYOUT_ORIGIN_X_MM,
        auto_layout_origin_y_mm=AUTO_LAYOUT_ORIGIN_Y_MM,
        auto_layout_column_spacing_mm=AUTO_LAYOUT_COLUMN_SPACING_MM,
        auto_layout_row_spacing_mm=AUTO_LAYOUT_ROW_SPACING_MM,
        warn=logger.warning,
    )
    schematic_layout_automation.register(
        mcp,
        schematic_layout_automation.SchematicLayoutAutomationDependencies(
            service=layout_automation_service,
        ),
    )


def register(mcp: FastMCP) -> None:
    """Register schematic tools."""
    _register_inspection_and_analysis(mcp)
    _register_authoring(mcp)

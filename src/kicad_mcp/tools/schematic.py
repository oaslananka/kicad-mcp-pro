"""Schematic tools with parser-based reads and transactional writes."""

from __future__ import annotations

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
    GetSheetInfoInput,
    GlobalLabelInput,
    HierarchicalLabelInput,
    PowerSymbolInput,
    RouteWireBetweenPinsInput,
    TraceNetInput,
    UpdatePropertiesInput,
)
from ..utils.sexpr import (
    _escape_sexpr_string,
    _extract_block,
    _sexpr_string,
    _unescape_sexpr_string,
)

SCHEMATIC_GRID_MM = 2.54
SNAP_TOLERANCE_MM = 1e-6
AUTO_LAYOUT_ORIGIN_X_MM = 50.8
AUTO_LAYOUT_ORIGIN_Y_MM = 50.8
AUTO_LAYOUT_COLUMN_SPACING_MM = 25.4
AUTO_LAYOUT_ROW_SPACING_MM = 17.78
AUTO_LAYOUT_COLUMNS = 4
DEFAULT_SHEET_WIDTH_MM = 30.48
DEFAULT_SHEET_HEIGHT_MM = 20.32
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

            return {
                "uuid": compatibility["uuid"],
                "symbols": symbols,
                "power_symbols": power_symbols,
                "wires": [
                    {
                        "x1": round(float(wire.start.x), 4),
                        "y1": round(float(wire.start.y), 4),
                        "x2": round(float(wire.end.x), 4),
                        "y2": round(float(wire.end.y), 4),
                    }
                    for wire in cast(list[_WireLike], list(schematic.wires.all()))
                ],
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
    generated_positions = {
        reference: _netlist_layout_point(index) for index, reference in enumerate(ordered_refs)
    }
    symbol_positions: dict[str, tuple[float, float]] = {}
    for symbol in laid_out_symbols:
        reference = str(symbol.get("reference", ""))
        if not _has_point(symbol):
            x, y = generated_positions.get(reference, _netlist_layout_point(len(symbol_positions)))
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

    for index, symbol in enumerate(laid_out_symbols):
        x, y = _auto_layout_point(index)
        symbol["x_mm"] = x
        symbol["y_mm"] = y
        symbol.setdefault("snap_to_grid", True)

    symbol_rows = max(1, math.ceil(max(len(laid_out_symbols), 1) / AUTO_LAYOUT_COLUMNS))
    gnd_y = AUTO_LAYOUT_ORIGIN_Y_MM + (symbol_rows * AUTO_LAYOUT_ROW_SPACING_MM)
    positive_y = AUTO_LAYOUT_ORIGIN_Y_MM - AUTO_LAYOUT_ROW_SPACING_MM
    for index, power_symbol in enumerate(laid_out_powers):
        x, _ = _auto_layout_point(index)
        name = str(power_symbol.get("name", "")).upper()
        power_symbol["x_mm"] = x
        power_symbol["y_mm"] = gnd_y if name.startswith("GND") else positive_y
        power_symbol.setdefault("snap_to_grid", True)

    label_y = gnd_y + AUTO_LAYOUT_ROW_SPACING_MM
    for index, label in enumerate(laid_out_labels):
        x, _ = _auto_layout_point(index)
        label["x_mm"] = x
        label["y_mm"] = label_y
        label.setdefault("snap_to_grid", True)

    return laid_out_symbols, laid_out_powers, laid_out_labels


def _read_schematic_compatibility_data(sch_file: Path) -> dict[str, Any]:
    """Read schematic data that kicad-sch-api 0.5.x does not yet surface directly."""
    content = sch_file.read_text(encoding="utf-8", errors="ignore")
    return {
        "uuid": _extract_uuid(content),
        "labels": _extract_labels(content),
        "buses": _extract_buses(content),
    }


def parse_schematic_file(sch_file: Path) -> dict[str, Any]:
    """Parse a schematic file through the active backend adapter."""
    return get_schematic_backend().parse_schematic_file(sch_file)


def _extract_uuid(content: str) -> str:
    match = re.search(r'\(kicad_sch[^(]*\(uuid\s+"([^"]+)"', content)
    return match.group(1) if match else ""


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
    library, _, symbol_name = lib_id.partition(":")
    return library, symbol_name or lib_id


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


def _find_placed_symbol_block(
    content: str, reference: str
) -> tuple[str, int, int, dict[str, Any]] | None:
    """Locate a placed symbol instance block by reference designator."""
    cursor = 0
    while cursor < len(content):
        if content[cursor:].startswith("(symbol"):
            block, length = _extract_block(content, cursor)
            if block:
                parsed = _parse_symbol_block(block)
                if parsed is not None and parsed["reference"] == reference:
                    return block, cursor, cursor + length, parsed
                cursor += length
                continue
        cursor += 1
    return None


def _transactional_write_to_schematic(mutator: Callable[[str], str]) -> str:
    """Read, mutate, validate, and atomically rewrite the active schematic."""
    sch_file = _get_schematic_file()
    current = sch_file.read_text(encoding="utf-8")
    updated = mutator(current)
    _validate_schematic_text(updated)
    with NamedTemporaryFile("w", encoding="utf-8", delete=False, dir=sch_file.parent) as handle:
        handle.write(updated)
        temp_path = Path(handle.name)
    temp_path.replace(sch_file)
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
        lines.extend(
            f"- ({wire['x1']}, {wire['y1']}) -> ({wire['x2']}, {wire['y2']})" for wire in wires
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
        root_uuid = parse_schematic_file(sch_file)["uuid"] or new_uuid()
        cfg = get_config()
        project_name = cfg.project_file.stem if cfg.project_file is not None else "KiCadMCP"
        lib_id = f"{payload.library}:{payload.symbol_name}"

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
        return f"{result}\n{snap_note}" if snap_note else result

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
    def sch_update_properties(reference: str, field: str, value: str) -> str:
        """Update a property on a placed symbol."""
        result = update_symbol_property(reference, field, value)
        return f"{result}\n{_reload_schematic()}"

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
        """Build a schematic from structured symbol, wire, and label inputs.

        Coordinates are snapped to the 2.54 mm grid by default.
        Set auto_layout=True to place symbols in a readable grid. If nets are provided,
        the layout is connection-aware and generates Manhattan wire segments from symbol pins.
        Nets that cannot resolve to at least two routable endpoints raise a clear error instead
        of silently producing a disconnected label-only schematic.
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

        segments = _manhattan_segments(start, end, payload.snap_to_grid)
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
        )

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
        """Auto-place selected references using deterministic cluster, linear, or star layouts."""
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

        requested = payload.symbol_list or [
            str(symbol["reference"]) for symbol in parse_schematic_file(sch_file)["symbols"]
        ]
        if not requested:
            return "The active schematic contains no symbols to auto-place."

        placed = 0
        missing: list[str] = []
        radius_mm = AUTO_LAYOUT_COLUMN_SPACING_MM
        center_x = AUTO_LAYOUT_ORIGIN_X_MM + AUTO_LAYOUT_COLUMN_SPACING_MM
        center_y = AUTO_LAYOUT_ORIGIN_Y_MM + AUTO_LAYOUT_ROW_SPACING_MM

        for index, reference in enumerate(requested):
            component = schematic.components.get(reference)
            if component is None:
                missing.append(reference)
                continue

            if payload.strategy == "linear":
                x = AUTO_LAYOUT_ORIGIN_X_MM + (index * AUTO_LAYOUT_COLUMN_SPACING_MM)
                y = AUTO_LAYOUT_ORIGIN_Y_MM
            elif payload.strategy == "star":
                if index == 0:
                    x = center_x
                    y = center_y
                else:
                    angle = ((index - 1) / max(len(requested) - 1, 1)) * (2 * math.pi)
                    x = center_x + (radius_mm * math.cos(angle))
                    y = center_y + (radius_mm * math.sin(angle))
            else:
                x, y = _auto_layout_point(index)

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
            f"{result}\nAuto-placed {placed} symbol(s) using the {payload.strategy} strategy."
            f"{missing_suffix}"
        )

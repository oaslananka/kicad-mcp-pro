# pyright: reportPrivateUsage=false

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from kicad_mcp.tools.metadata import get_tool_metadata
from kicad_mcp.tools.schematic_connectivity_authoring import (
    SchematicConnectivityAuthoringDependencies,
    register,
)


class FakeConnectivityAuthoringService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def add_pin_labels(
        self,
        connections: list[dict[str, Any]],
        stub_mm: float = 5.08,
        global_labels: bool = True,
        sheet: str | None = None,
        sheet_file: str | None = None,
        label_kind: str | None = None,
    ) -> str:
        self.calls.append(
            (
                "add_pin_labels",
                {
                    "connections": connections,
                    "stub_mm": stub_mm,
                    "global_labels": global_labels,
                    "sheet": sheet,
                    "sheet_file": sheet_file,
                    "label_kind": label_kind,
                },
            )
        )
        return "pin-labels"

    def route_wire_between_pins(
        self,
        ref1: str,
        pin1: str,
        ref2: str,
        pin2: str,
        snap_to_grid: bool = True,
    ) -> str:
        self.calls.append(
            (
                "route_wire_between_pins",
                {
                    "ref1": ref1,
                    "pin1": pin1,
                    "ref2": ref2,
                    "pin2": pin2,
                    "snap_to_grid": snap_to_grid,
                },
            )
        )
        return "routed"

    def add_missing_junctions(self) -> str:
        self.calls.append(("add_missing_junctions", {}))
        return "junctions"


def _registered() -> tuple[FastMCP, FakeConnectivityAuthoringService]:
    server = FastMCP("schematic-connectivity-authoring-test")
    service = FakeConnectivityAuthoringService()
    register(server, SchematicConnectivityAuthoringDependencies(service=service))  # type: ignore[arg-type]
    return server, service


def test_registration_preserves_names_descriptions_and_schemas() -> None:
    server, _service = _registered()
    tools = {tool.name: tool for tool in server._tool_manager.list_tools()}

    assert set(tools) == {
        "sch_add_pin_labels",
        "sch_route_wire_between_pins",
        "sch_add_missing_junctions",
    }
    assert tools["sch_add_pin_labels"].description == (
        "Connect placed-symbol pins to nets with a short outward wire stub plus a\n"
        "terminal placed clear of the symbol body (avoids label-on-pin overlap).\n\n"
        'Each connection is ``{"reference": "U3", "pin": "VIN" | "5", "net":\n'
        '"5V_SYS"}``; the pin may be a number or a name. The stub direction is\n'
        "derived from the symbol edge the pin sits on, so the terminal lands outside\n"
        "the symbol and reads outward. Power nets get conventional power symbols;\n"
        "other nets get labels. Pins that share a ``net`` are joined by their\n"
        "common terminal name. This is the clean alternative to placing bare\n"
        "labels directly on pins.\n\n"
        "``label_kind`` selects the emitted label type for non-power nets:\n"
        '``"local"``, ``"global"``, or ``"hierarchical"``. When set it takes\n'
        "precedence over the legacy ``global_labels`` boolean, enabling batch\n"
        "placement of hierarchical labels at sheet boundaries. A hierarchical\n"
        'connection may add an optional ``"shape"`` (e.g. ``"input"``,\n'
        '``"output"``, ``"bidirectional"``) passed through to the label.\n'
    )
    assert tools["sch_route_wire_between_pins"].description == (
        "Route deterministic Manhattan wire segments between two placed symbol pins."
    )
    assert tools["sch_add_missing_junctions"].description == (
        "Insert missing schematic junctions at T-intersection wire endpoints."
    )

    assert tools["sch_add_pin_labels"].parameters == {
        "properties": {
            "connections": {
                "items": {"additionalProperties": True, "type": "object"},
                "title": "Connections",
                "type": "array",
            },
            "stub_mm": {"default": 5.08, "title": "Stub Mm", "type": "number"},
            "global_labels": {
                "default": True,
                "title": "Global Labels",
                "type": "boolean",
            },
            "sheet": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
                "title": "Sheet",
            },
            "sheet_file": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
                "title": "Sheet File",
            },
            "label_kind": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
                "title": "Label Kind",
            },
        },
        "required": ["connections"],
        "title": "sch_add_pin_labelsArguments",
        "type": "object",
    }
    assert tools["sch_route_wire_between_pins"].parameters == {
        "properties": {
            "ref1": {"title": "Ref1", "type": "string"},
            "pin1": {"title": "Pin1", "type": "string"},
            "ref2": {"title": "Ref2", "type": "string"},
            "pin2": {"title": "Pin2", "type": "string"},
            "snap_to_grid": {
                "default": True,
                "title": "Snap To Grid",
                "type": "boolean",
            },
        },
        "required": ["ref1", "pin1", "ref2", "pin2"],
        "title": "sch_route_wire_between_pinsArguments",
        "type": "object",
    }
    assert tools["sch_add_missing_junctions"].parameters == {
        "properties": {},
        "title": "sch_add_missing_junctionsArguments",
        "type": "object",
    }
    for name, tool in tools.items():
        assert tool.output_schema == {
            "properties": {"result": {"title": "Result", "type": "string"}},
            "required": ["result"],
            "title": f"{name}Output",
            "type": "object",
        }
        assert tool.annotations is None


def test_registration_preserves_headless_metadata() -> None:
    server, _service = _registered()
    metadata = {
        tool.name: get_tool_metadata(tool.name) for tool in server._tool_manager.list_tools()
    }

    assert metadata["sch_add_pin_labels"] is None
    assert metadata["sch_route_wire_between_pins"] is None
    junctions = metadata["sch_add_missing_junctions"]
    assert junctions is not None
    assert junctions.headless_compatible is True
    assert junctions.requires_kicad_running is False


def test_registration_delegates_exact_arguments() -> None:
    server, service = _registered()
    tools = {tool.name: tool for tool in server._tool_manager.list_tools()}

    assert (
        tools["sch_add_pin_labels"].fn(
            connections=[{"reference": "U1", "pin": "1", "net": "3V3"}],
            stub_mm=7.62,
            global_labels=False,
            sheet="Power",
            sheet_file=None,
        )
        == "pin-labels"
    )
    assert (
        tools["sch_route_wire_between_pins"].fn(
            ref1="U1",
            pin1="1",
            ref2="R1",
            pin2="2",
            snap_to_grid=False,
        )
        == "routed"
    )
    assert tools["sch_add_missing_junctions"].fn() == "junctions"

    assert service.calls == [
        (
            "add_pin_labels",
            {
                "connections": [{"reference": "U1", "pin": "1", "net": "3V3"}],
                "stub_mm": 7.62,
                "global_labels": False,
                "sheet": "Power",
                "sheet_file": None,
                "label_kind": None,
            },
        ),
        (
            "route_wire_between_pins",
            {
                "ref1": "U1",
                "pin1": "1",
                "ref2": "R1",
                "pin2": "2",
                "snap_to_grid": False,
            },
        ),
        ("add_missing_junctions", {}),
    ]

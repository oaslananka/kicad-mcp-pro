from __future__ import annotations

from pathlib import Path

import pytest
from mcp.server.fastmcp import FastMCP
from pydantic import ValidationError

from kicad_mcp.tools.schematic_topology import (
    SchematicTopologyDependencies,
    register,
)


class FakeTopologyService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    def list_sheets(self, path: Path) -> str:
        self.calls.append(("list_sheets", (path,)))
        return "sheets"

    def sheet_info(self, path: Path, sheet_name: str) -> str:
        self.calls.append(("sheet_info", (path, sheet_name)))
        return "sheet-info"

    def connectivity_graph(self, path: Path) -> str:
        self.calls.append(("connectivity_graph", (path,)))
        return "graph"

    def trace_net(self, path: Path, net_name: str) -> str:
        self.calls.append(("trace_net", (path, net_name)))
        return "trace"


def _registered() -> tuple[FastMCP, FakeTopologyService]:
    server = FastMCP("schematic-topology-test")
    service = FakeTopologyService()
    register(
        server,
        SchematicTopologyDependencies(
            active_schematic_file=lambda: Path("active.kicad_sch"),
            service=service,
        ),
    )
    return server, service


def test_registration_preserves_names_descriptions_and_schemas() -> None:
    server, _service = _registered()
    tools = {tool.name: tool for tool in server._tool_manager.list_tools()}

    assert set(tools) == {
        "sch_list_sheets",
        "sch_get_sheet_info",
        "sch_get_connectivity_graph",
        "sch_trace_net",
    }
    assert tools["sch_list_sheets"].description == (
        "List child sheets from the active top-level schematic."
    )
    assert tools["sch_get_sheet_info"].description == (
        "Return metadata for a specific child sheet."
    )
    assert tools["sch_get_connectivity_graph"].description == (
        "Summarize the active schematic as a textual net connectivity graph."
    )
    assert tools["sch_trace_net"].description == (
        "Trace a named net through the active schematic and matching child sheets."
    )
    assert tools["sch_list_sheets"].parameters["properties"] == {}
    assert tools["sch_get_sheet_info"].parameters["required"] == ["sheet_name"]
    assert tools["sch_trace_net"].parameters["required"] == ["net_name"]
    assert tools["sch_get_sheet_info"].parameters["properties"]["sheet_name"] == {
        "title": "Sheet Name",
        "type": "string",
    }
    assert tools["sch_trace_net"].parameters["properties"]["net_name"] == {
        "title": "Net Name",
        "type": "string",
    }


def test_registration_delegates_to_active_schematic() -> None:
    server, service = _registered()
    tools = {tool.name: tool for tool in server._tool_manager.list_tools()}

    assert tools["sch_list_sheets"].fn() == "sheets"
    assert tools["sch_get_sheet_info"].fn(sheet_name="Power") == "sheet-info"
    assert tools["sch_get_connectivity_graph"].fn() == "graph"
    assert tools["sch_trace_net"].fn(net_name="VCC") == "trace"
    assert service.calls == [
        ("list_sheets", (Path("active.kicad_sch"),)),
        ("sheet_info", (Path("active.kicad_sch"), "Power")),
        ("connectivity_graph", (Path("active.kicad_sch"),)),
        ("trace_net", (Path("active.kicad_sch"), "VCC")),
    ]


def test_registration_preserves_pydantic_validation() -> None:
    server, _service = _registered()
    tools = {tool.name: tool for tool in server._tool_manager.list_tools()}

    with pytest.raises(ValidationError):
        tools["sch_get_sheet_info"].fn(sheet_name="")
    with pytest.raises(ValidationError):
        tools["sch_trace_net"].fn(net_name="")

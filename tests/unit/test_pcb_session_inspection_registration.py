# pyright: reportPrivateUsage=false

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from kicad_mcp.tools.metadata import get_tool_metadata
from kicad_mcp.tools.pcb_session_inspection import PcbSessionInspectionDependencies, register


class FakeSessionInspectionService:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def get_selection(self) -> str:
        self.calls.append("selection")
        return "selection"

    def get_board_as_string(self) -> str:
        self.calls.append("board")
        return "board"


def test_registration_preserves_contract_metadata_and_forwarding() -> None:
    server = FastMCP("pcb-session-inspection-test")
    service = FakeSessionInspectionService()
    register(server, PcbSessionInspectionDependencies(service=service))
    tools = {tool.name: tool for tool in server._tool_manager.list_tools()}

    assert set(tools) == {"pcb_get_selection", "pcb_get_board_as_string"}
    for name in tools:
        assert tools[name].parameters["properties"] == {}
        assert "required" not in tools[name].parameters
    assert tools["pcb_get_selection"].description == (
        "List currently selected items in the PCB editor."
    )
    assert tools["pcb_get_board_as_string"].description == (
        "Return the current board as a bounded S-expression string."
    )
    assert tools["pcb_get_selection"].fn() == "selection"
    assert tools["pcb_get_board_as_string"].fn() == "board"
    assert service.calls == ["selection", "board"]

    for name in tools:
        metadata = get_tool_metadata(name)
        assert metadata is not None
        assert metadata.headless_compatible is True
        assert metadata.requires_kicad_running is False

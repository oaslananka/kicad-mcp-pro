# pyright: reportPrivateUsage=false

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from kicad_mcp.tools.metadata import get_tool_metadata
from kicad_mcp.tools.pcb_groups_inspection import PcbGroupsInspectionDependencies, register


class FakeGroupsService:
    def __init__(self) -> None:
        self.calls = 0

    def get_groups(self) -> str:
        self.calls += 1
        return "groups"


def test_registration_preserves_contract_metadata_and_forwarding() -> None:
    server = FastMCP("pcb-groups-inspection-test")
    service = FakeGroupsService()
    register(server, PcbGroupsInspectionDependencies(service=service))
    tools = {tool.name: tool for tool in server._tool_manager.list_tools()}

    assert set(tools) == {"pcb_get_groups"}
    tool = tools["pcb_get_groups"]
    assert tool.parameters == {
        "properties": {},
        "title": "pcb_get_groupsArguments",
        "type": "object",
    }
    assert tool.description == (
        "List board groups (KiCad 10.0.0+).\n\n"
        "Groups are logical collections of board items that can be moved and\n"
        "manipulated together.\n\n"
        "Returns:\n"
        "    JSON string with group information or message if not supported.\n"
    )
    assert tool.fn() == "groups"
    assert service.calls == 1

    metadata = get_tool_metadata("pcb_get_groups")
    assert metadata is not None
    assert metadata.headless_compatible is True
    assert metadata.requires_kicad_running is False

# pyright: reportPrivateUsage=false

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from kicad_mcp.tools.metadata import get_tool_metadata
from kicad_mcp.tools.pcb_basic_inspection import PcbBasicInspectionDependencies, register


class FakeBasicInspectionService:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def get_nets(self) -> str:
        self.calls.append("nets")
        return "nets"

    def get_zones(self) -> str:
        self.calls.append("zones")
        return "zones"

    def get_shapes(self) -> str:
        self.calls.append("shapes")
        return "shapes"

    def get_pads(self) -> str:
        self.calls.append("pads")
        return "pads"

    def get_layers(self) -> str:
        self.calls.append("layers")
        return "layers"


def test_registration_preserves_contract_metadata_and_forwarding() -> None:
    server = FastMCP("pcb-basic-inspection-test")
    service = FakeBasicInspectionService()
    register(server, PcbBasicInspectionDependencies(service=service))
    tools = {tool.name: tool for tool in server._tool_manager.list_tools()}
    expected = {
        "pcb_get_nets": "List all board nets.",
        "pcb_get_zones": "List all board copper zones.",
        "pcb_get_shapes": "List graphical board shapes.",
        "pcb_get_pads": "List board pads.",
        "pcb_get_layers": "List enabled board layers.",
    }
    assert set(tools) == set(expected)
    for name, description in expected.items():
        assert tools[name].description == description
        assert tools[name].parameters["properties"] == {}
        assert "required" not in tools[name].parameters

    assert tools["pcb_get_nets"].fn() == "nets"
    assert tools["pcb_get_zones"].fn() == "zones"
    assert tools["pcb_get_shapes"].fn() == "shapes"
    assert tools["pcb_get_pads"].fn() == "pads"
    assert tools["pcb_get_layers"].fn() == "layers"
    assert service.calls == ["nets", "zones", "shapes", "pads", "layers"]

    for name in ("pcb_get_nets", "pcb_get_zones", "pcb_get_layers"):
        metadata = get_tool_metadata(name)
        assert metadata is not None
        assert metadata.headless_compatible is True
        assert metadata.requires_kicad_running is False
    for name in ("pcb_get_shapes", "pcb_get_pads"):
        metadata = get_tool_metadata(name)
        assert metadata is not None
        assert metadata.requires_kicad_running is True
        assert metadata.headless_compatible is False

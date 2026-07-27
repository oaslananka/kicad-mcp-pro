# pyright: reportPrivateUsage=false

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from kicad_mcp.tools.metadata import get_tool_metadata
from kicad_mcp.tools.pcb_stackup_management import PcbStackupDependencies, register


class FakeStackupService:
    def __init__(self) -> None:
        self.calls: list[object] = []

    def get_stackup(self) -> str:
        self.calls.append("get")
        return "stackup"

    def set_stackup(self, layers: list[dict[str, object]]) -> str:
        self.calls.append(("set", layers))
        return "updated"


def test_registration_preserves_contract_metadata_and_forwarding() -> None:
    server = FastMCP("pcb-stackup-management-test")
    service = FakeStackupService()
    register(server, PcbStackupDependencies(service=service))
    tools = {tool.name: tool for tool in server._tool_manager.list_tools()}

    assert set(tools) == {"pcb_get_stackup", "pcb_set_stackup"}
    assert tools["pcb_get_stackup"].description == "Show the current stackup."
    assert tools["pcb_set_stackup"].description == (
        "Set the active board stackup using a file-backed profile."
    )
    assert tools["pcb_get_stackup"].parameters == {
        "properties": {},
        "title": "pcb_get_stackupArguments",
        "type": "object",
    }
    assert tools["pcb_set_stackup"].parameters == {
        "properties": {
            "layers": {
                "items": {"additionalProperties": True, "type": "object"},
                "title": "Layers",
                "type": "array",
            }
        },
        "required": ["layers"],
        "title": "pcb_set_stackupArguments",
        "type": "object",
    }

    layers: list[dict[str, object]] = [{"name": "F_Cu"}, {"name": "B_Cu"}]
    assert tools["pcb_get_stackup"].fn() == "stackup"
    assert tools["pcb_set_stackup"].fn(layers) == "updated"
    assert service.calls == ["get", ("set", layers)]

    for name in tools:
        metadata = get_tool_metadata(name)
        assert metadata is not None
        assert metadata.headless_compatible is True
        assert metadata.requires_kicad_running is False

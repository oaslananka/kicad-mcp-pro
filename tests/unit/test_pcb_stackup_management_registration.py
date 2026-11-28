# pyright: reportPrivateUsage=false

from __future__ import annotations

from jsonschema import Draft202012Validator
from mcp.server.mcpserver import MCPServer as FastMCP

from kicad_mcp.models.pcb import KeepoutLayerIntents
from kicad_mcp.tools.metadata import get_tool_metadata
from kicad_mcp.tools.pcb_stackup_management import PcbStackupDependencies, register


class FakeStackupService:
    def __init__(self) -> None:
        self.calls: list[object] = []

    def get_stackup(self) -> str:
        self.calls.append("get")
        return "stackup"

    def set_stackup(
        self,
        layers: list[dict[str, object]],
        allow_open_board: bool = False,
        keepout_layer_intents: KeepoutLayerIntents | None = None,
    ) -> str:
        self.calls.append(("set", layers, allow_open_board, keepout_layer_intents))
        return "updated"


def test_registration_preserves_contract_metadata_and_forwarding() -> None:
    server = FastMCP("pcb-stackup-management-test")
    service = FakeStackupService()
    register(server, PcbStackupDependencies(service=service))
    tools = {tool.name: tool for tool in server._tool_manager.list_tools()}

    assert set(tools) == {"pcb_get_stackup", "pcb_set_stackup"}
    assert tools["pcb_get_stackup"].description == "Show the current stackup."
    description = tools["pcb_set_stackup"].description
    assert description is not None
    assert description.startswith("Set the active board stackup using a file-backed profile.")
    assert "allow_open_board=True" in description
    assert tools["pcb_get_stackup"].parameters == {
        "properties": {},
        "title": "pcb_get_stackupArguments",
        "type": "object",
    }
    schema = tools["pcb_set_stackup"].parameters
    assert schema["required"] == ["layers"]
    assert set(schema["properties"]) == {"layers", "allow_open_board", "keepout_layer_intents"}
    validator = Draft202012Validator(schema)
    layers: list[dict[str, object]] = [{"name": "F_Cu"}, {"name": "B_Cu"}]
    decision = {
        "33333333-3333-4333-8333-333333333333/11111111-1111-4111-8111-111111111111": "all_copper"
    }
    assert validator.is_valid({"layers": layers})
    assert validator.is_valid({"layers": layers, "keepout_layer_intents": decision})
    assert not validator.is_valid({"layers": layers, "keepout_layer_intents": {"x": "unknown"}})
    assert tools["pcb_get_stackup"].fn() == "stackup"
    assert tools["pcb_set_stackup"].fn(layers) == "updated"
    assert tools["pcb_set_stackup"].fn(layers, allow_open_board=True) == "updated"
    assert tools["pcb_set_stackup"].fn(layers, keepout_layer_intents=decision) == "updated"
    assert service.calls == [
        "get",
        ("set", layers, False, None),
        ("set", layers, True, None),
        ("set", layers, False, decision),
    ]

    for name in tools:
        metadata = get_tool_metadata(name)
        assert metadata is not None
        assert metadata.headless_compatible is True
        assert metadata.requires_kicad_running is False

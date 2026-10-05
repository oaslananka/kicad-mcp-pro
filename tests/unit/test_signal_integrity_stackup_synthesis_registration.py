from __future__ import annotations

import importlib
import inspect

from mcp.server.mcpserver import MCPServer as FastMCP


class FakeService:
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []

    def synthesize(
        self,
        interfaces: list[dict[str, object]],
        cost_tier: str = "standard",
        board_thickness_mm: float = 1.6,
    ) -> str:
        self.calls.append((interfaces, cost_tier, board_thickness_mm))
        return "stackup-result"


def test_registration_preserves_signature_docstring_order_and_delegation() -> None:
    adapter = importlib.import_module("kicad_mcp.tools.signal_integrity_stackup_synthesis")
    server = FastMCP("si-stackup-synthesis-registration")
    service = FakeService()

    adapter.register(
        server,
        adapter.SignalIntegrityStackupSynthesisDependencies(service=service),
    )

    tool_list = server._tool_manager.list_tools()
    assert [tool.name for tool in tool_list] == ["si_synthesize_stackup_for_interfaces"]

    tool = tool_list[0]
    assert str(inspect.signature(tool.fn)) == (
        "(interfaces: 'list[dict[str, object]]', cost_tier: 'str' = 'standard', "
        "board_thickness_mm: 'float' = 1.6) -> 'str'"
    )
    assert tool.fn.__doc__ is not None
    assert tool.fn.__doc__.startswith(
        "Synthesise a PCB stackup that meets the impedance requirements"
    )

    interfaces = [{"kind": "usb3", "differential": True}]
    assert tool.fn(interfaces, "midloss", 1.2) == "stackup-result"
    assert service.calls == [(interfaces, "midloss", 1.2)]

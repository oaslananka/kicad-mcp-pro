from __future__ import annotations

import importlib
import inspect

from mcp.server.mcpserver import MCPServer as FastMCP


class FakeService:
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []

    def generate(
        self,
        layer_count: int,
        target_impedance_ohm: float,
        manufacturer: str,
        er: float,
        copper_oz: float,
    ) -> str:
        self.calls.append((layer_count, target_impedance_ohm, manufacturer, er, copper_oz))
        return "stackup-result"


def test_registration_preserves_signature_docstring_order_and_delegation() -> None:
    adapter = importlib.import_module("kicad_mcp.tools.signal_integrity_stackup_generation")
    server = FastMCP("si-stackup-generation-registration")
    service = FakeService()

    adapter.register(
        server,
        adapter.SignalIntegrityStackupGenerationDependencies(service=service),
    )

    tools = server._tool_manager.list_tools()
    assert [tool.name for tool in tools] == ["si_generate_stackup"]

    tool = tools[0]
    assert str(inspect.signature(tool.fn)) == (
        "(layer_count: 'int' = 4, target_impedance_ohm: 'float' = 50.0, "
        "manufacturer: 'str' = 'JLCPCB', er: 'float' = 4.2, "
        "copper_oz: 'float' = 1.0) -> 'str'"
    )
    assert (
        tool.fn.__doc__
        == "Generate a practical board stackup recommendation and target trace geometry."
    )

    assert tool.fn(6, 55.0, "PCBWay", 4.1, 0.5) == "stackup-result"
    assert service.calls == [(6, 55.0, "PCBWay", 4.1, 0.5)]

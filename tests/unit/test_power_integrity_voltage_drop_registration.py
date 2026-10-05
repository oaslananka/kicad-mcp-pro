from __future__ import annotations

import importlib
import inspect

from mcp.server.mcpserver import MCPServer as FastMCP


class FakeService:
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []

    def calculate_voltage_drop(
        self,
        current_a: float,
        trace_width_mm: float,
        trace_length_mm: float,
        copper_oz: float,
        max_temp_rise_c: float,
        internal_layer: bool,
    ) -> str:
        self.calls.append(
            (
                current_a,
                trace_width_mm,
                trace_length_mm,
                copper_oz,
                max_temp_rise_c,
                internal_layer,
            )
        )
        return "voltage-drop-result"


def test_registration_preserves_signature_docstring_and_delegation() -> None:
    adapter = importlib.import_module("kicad_mcp.tools.power_integrity_voltage_drop")
    server = FastMCP("pi-voltage-drop-registration")
    service = FakeService()

    adapter.register(
        server,
        adapter.PowerIntegrityVoltageDropDependencies(service=service),
    )

    tools = server._tool_manager.list_tools()
    assert [tool.name for tool in tools] == ["pdn_calculate_voltage_drop"]

    tool = tools[0]
    assert str(inspect.signature(tool.fn)) == (
        "(current_a: 'float', trace_width_mm: 'float', trace_length_mm: 'float', "
        "copper_oz: 'float' = 1.0, max_temp_rise_c: 'float' = 10.0, "
        "internal_layer: 'bool' = False) -> 'str'"
    )
    assert tool.fn.__doc__ is not None
    assert tool.fn.__doc__.startswith(
        "Estimate DC voltage drop, trace resistance, and IPC-2221 current-density fusing."
    )

    assert tool.fn(1.0, 0.5, 100.0) == "voltage-drop-result"
    assert service.calls == [(1.0, 0.5, 100.0, 1.0, 10.0, False)]

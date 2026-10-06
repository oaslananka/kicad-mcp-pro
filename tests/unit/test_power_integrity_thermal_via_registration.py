from __future__ import annotations

import importlib
import inspect
from types import SimpleNamespace
from typing import Any, cast

from mcp.server.mcpserver import MCPServer as FastMCP

from kicad_mcp.models.power_integrity import ThermalViaInput


class FakeService:
    def __init__(self) -> None:
        self.calls: list[tuple[ThermalViaInput, float]] = []

    def estimate(self, payload: ThermalViaInput, *, board_thickness_mm: float) -> str:
        self.calls.append((payload, board_thickness_mm))
        return "thermal-via-result"


def test_registration_preserves_signature_docstring_and_delegation() -> None:
    adapter = importlib.import_module("kicad_mcp.tools.power_integrity_thermal_via")
    server = FastMCP("pi-thermal-via-registration")
    service = FakeService()
    adapter.register(server, cast(Any, service), board_thickness_provider=lambda: 1.2)

    tools = server._tool_manager.list_tools()
    assert [tool.name for tool in tools] == ["thermal_calculate_via_count"]
    tool = tools[0]
    assert str(inspect.signature(tool.fn)) == (
        "(power_w: 'float | None' = None, package_power_w: 'float | None' = None, "
        "ambient_c: 'float' = 25.0, max_junction_c: 'float' = 125.0, "
        "theta_ja_deg_c_w: 'float' = 40.0, via_diameter_mm: 'float' = 0.3, "
        "thermal_resistance_target: 'float' = 5.0) -> 'str'"
    )
    assert tool.fn.__doc__ == (
        "Estimate thermal via count from package heat and board thermal resistance."
    )

    assert tool.fn(power_w=2.0) == "thermal-via-result"
    assert len(service.calls) == 1
    payload, thickness = service.calls[0]
    assert payload.power_w == 2.0
    assert payload.package_power_w is None
    assert payload.ambient_c == 25.0
    assert payload.max_junction_c == 125.0
    assert payload.theta_ja_deg_c_w == 40.0
    assert payload.via_diameter_mm == 0.3
    assert payload.thermal_resistance_target == 5.0
    assert thickness == 1.2


def test_board_thickness_provider_uses_stackup_and_default(monkeypatch) -> None:
    adapter = importlib.import_module("kicad_mcp.tools.power_integrity_thermal_via")

    board = SimpleNamespace(
        get_stackup=lambda: SimpleNamespace(
            layers=[SimpleNamespace(thickness=800_000), SimpleNamespace(thickness=700_000)]
        )
    )
    monkeypatch.setattr(adapter, "get_board", lambda: board)
    assert adapter._board_thickness_mm() == 1.5

    empty_board = SimpleNamespace(get_stackup=lambda: SimpleNamespace(layers=[]))
    monkeypatch.setattr(adapter, "get_board", lambda: empty_board)
    assert adapter._board_thickness_mm() == adapter.DEFAULT_BOARD_THICKNESS_MM

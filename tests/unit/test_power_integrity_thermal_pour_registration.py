from __future__ import annotations

import importlib
import inspect
from types import SimpleNamespace
from typing import Any, cast

from kipy.proto.board.board_types_pb2 import BoardLayer
from mcp.server.mcpserver import MCPServer as FastMCP

from kicad_mcp.models.power_integrity import ThermalPourInput
from kicad_mcp.models.verdict import VerdictReport
from kicad_mcp.power_integrity.thermal_pour import CopperPourObservation


class FakeService:
    def __init__(self) -> None:
        self.calls: list[tuple[ThermalPourInput, list[CopperPourObservation], int]] = []

    def analyze(
        self,
        payload: ThermalPourInput,
        pours: list[CopperPourObservation],
        *,
        max_items: int,
    ) -> VerdictReport:
        self.calls.append((payload, pours, max_items))
        return VerdictReport.from_text_verdict(
            text="thermal-pour-result",
            summary="thermal-pour-summary",
            verdict="PASS",
            source="thermal_check_copper_pour",
            metadata={"domain": "thermal"},
        )


def test_registration_preserves_signature_docstring_and_delegation() -> None:
    adapter = importlib.import_module("kicad_mcp.tools.power_integrity_thermal_pour")
    server = FastMCP("pi-thermal-pour-registration")
    service = FakeService()
    pours = [CopperPourObservation("Z1", ("BL_F_Cu",))]
    adapter.register(
        server,
        cast(Any, service),
        pour_provider=lambda net_name: pours if net_name == "3V3" else [],
        max_items_provider=lambda: 7,
    )

    tools = server._tool_manager.list_tools()
    assert [tool.name for tool in tools] == ["thermal_check_copper_pour"]
    tool = tools[0]
    assert str(inspect.signature(tool.fn)) == (
        "(net_name: 'str', expected_power_w: 'float', preferred_layer: 'str' = 'auto') "
        "-> 'VerdictReport'"
    )
    assert tool.fn.__doc__ == "Check whether the board already has copper pour support for the net."

    assert tool.fn("3V3", 2.0).text == "thermal-pour-result"
    assert len(service.calls) == 1
    payload, observed, max_items = service.calls[0]
    assert payload.net_name == "3V3"
    assert payload.expected_power_w == 2.0
    assert payload.preferred_layer == "auto"
    assert observed is pours
    assert max_items == 7


def test_default_pour_provider_filters_net_and_normalizes_layers(monkeypatch) -> None:
    adapter = importlib.import_module("kicad_mcp.tools.power_integrity_thermal_pour")
    board = object()
    zones = [
        SimpleNamespace(
            name="POWER",
            net=SimpleNamespace(name="3V3"),
            layers=[BoardLayer.BL_F_Cu, BoardLayer.BL_B_Cu],
        ),
        SimpleNamespace(name="GROUND", net=SimpleNamespace(name="GND"), layers=[]),
    ]
    calls: list[tuple[object, ...]] = []
    monkeypatch.setattr(adapter, "get_board", lambda: calls.append(("board",)) or board)
    monkeypatch.setattr(
        adapter,
        "board_zones",
        lambda value: calls.append(("zones", value is board)) or zones,
    )

    assert adapter._pour_observations("3V3") == [
        CopperPourObservation("POWER", ("BL_F_Cu", "BL_B_Cu"))
    ]
    assert calls == [("board",), ("zones", True)]

from __future__ import annotations

import importlib
import inspect
from types import SimpleNamespace
from typing import Any, cast

from kipy.proto.board.board_types_pb2 import BoardLayer
from mcp.server.mcpserver import MCPServer as FastMCP

from kicad_mcp.models.power_integrity import CopperWeightCheckInput
from kicad_mcp.models.verdict import VerdictReport
from kicad_mcp.power_integrity.copper_weight import CopperTrackObservation


class FakeService:
    def __init__(self) -> None:
        self.calls: list[tuple[CopperWeightCheckInput, list[CopperTrackObservation]]] = []

    def analyze(
        self,
        payload: CopperWeightCheckInput,
        tracks: list[CopperTrackObservation],
    ) -> VerdictReport:
        self.calls.append((payload, tracks))
        return VerdictReport.from_text_verdict(
            text="copper-result",
            summary="copper-summary",
            verdict="PASS",
            source="pdn_check_copper_weight",
            metadata={"domain": "power_integrity"},
        )


def test_registration_preserves_signature_docstring_and_delegation() -> None:
    adapter = importlib.import_module("kicad_mcp.tools.power_integrity_copper_weight")
    server = FastMCP("pi-copper-weight-registration")
    service = FakeService()
    observations = [
        CopperTrackObservation(0.5, 10.0, 0.035, True),
    ]
    adapter.register(
        server,
        cast(Any, service),
        track_provider=lambda net_name: observations if net_name == "3V3" else [],
    )

    tools = server._tool_manager.list_tools()
    assert [tool.name for tool in tools] == ["pdn_check_copper_weight"]
    tool = tools[0]
    assert str(inspect.signature(tool.fn)) == (
        "(net_name: 'str', expected_current_a: 'float', ambient_temp_c: 'float' = 25.0, "
        "max_temp_rise_c: 'float' = 10.0) -> 'VerdictReport'"
    )
    assert tool.fn.__doc__ == (
        "Check whether the routed copper for a net looks sufficient for the load current."
    )

    result = tool.fn("3V3", 0.5)
    assert result.text == "copper-result"
    assert len(service.calls) == 1
    payload, tracks = service.calls[0]
    assert payload.net_name == "3V3"
    assert payload.expected_current_a == 0.5
    assert payload.ambient_temp_c == 25.0
    assert payload.max_temp_rise_c == 10.0
    assert tracks is observations


def test_default_track_provider_snapshots_board_and_stackup_once(monkeypatch) -> None:
    adapter = importlib.import_module("kicad_mcp.tools.power_integrity_copper_weight")
    layer = BoardLayer.BL_F_Cu
    board = SimpleNamespace(
        get_stackup=lambda: SimpleNamespace(layers=[SimpleNamespace(layer=layer, thickness=35_000)])
    )
    tracks = [
        SimpleNamespace(
            net=SimpleNamespace(name="3V3"),
            width=500_000,
            layer=layer,
            start="a",
            end="b",
        ),
        SimpleNamespace(
            net=SimpleNamespace(name="GND"),
            width=250_000,
            layer=layer,
            start="c",
            end="d",
        ),
    ]
    calls: list[tuple[object, ...]] = []
    monkeypatch.setattr(adapter, "get_board", lambda: calls.append(("board",)) or board)
    monkeypatch.setattr(
        adapter,
        "board_tracks",
        lambda value: calls.append(("tracks", value is board)) or tracks,
    )
    monkeypatch.setattr(adapter, "track_segment_length_mm", lambda track: 12.0)

    observed = adapter._copper_track_observations("3V3")

    assert calls == [("board",), ("tracks", True)]
    assert observed == [CopperTrackObservation(0.5, 12.0, 0.035, True)]

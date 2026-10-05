from __future__ import annotations

import importlib
import inspect
from types import SimpleNamespace
from typing import Any, cast

import pytest
from kipy.proto.board.board_types_pb2 import ViaType
from mcp.server.mcpserver import MCPServer as FastMCP

from kicad_mcp.models.signal_integrity import ViaStubInput
from kicad_mcp.signal_integrity.via_stub import ViaStubObservation


class FakeService:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def analyze(self, **kwargs: object) -> str:
        self.calls.append(kwargs)
        return "via-result"


def test_registration_preserves_signature_docstring_and_delegation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = importlib.import_module("kicad_mcp.tools.signal_integrity_via_stub")
    service = FakeService()
    server = FastMCP("si-via-stub-registration")
    fake_via = SimpleNamespace()
    observation = ViaStubObservation(
        net_name="USB_DP",
        x_mm=1.0,
        y_mm=2.0,
        via_type_name="VT_THROUGH",
        drill_mm=0.3,
        stub_mm=1.6,
    )
    monkeypatch.setattr(adapter, "_selected_vias", lambda _positions: [fake_via])
    monkeypatch.setattr(adapter, "_board_thickness_mm", lambda: 1.6)
    monkeypatch.setattr(adapter, "_critical_frequencies_mhz", lambda: [23_420.0])
    monkeypatch.setattr(adapter, "_response_limit", lambda: 10)
    monkeypatch.setattr(adapter, "_via_observation", lambda _via: observation)

    adapter.register(
        server,
        adapter.SignalIntegrityViaStubDependencies(service=cast(Any, service)),
    )

    tool = server._tool_manager.list_tools()[0]
    assert tool.name == "si_check_via_stub"
    assert str(inspect.signature(tool.fn)) == (
        "(frequency_ghz: 'float', via_positions: 'list[_ViaPosition] | None' = None, "
        "er: 'float' = 4.0) -> 'str'"
    )
    assert tool.fn.__doc__ is not None
    assert tool.fn.__doc__.startswith(
        "Estimate via-stub resonance and risk for selected vias on the active board."
    )

    assert tool.fn(5.0, [[1.0, 2.0]], 4.0) == "via-result"
    assert len(service.calls) == 1
    call = service.calls[0]
    assert call["board_thickness_mm"] == 1.6
    assert call["observations"] == [observation]
    assert call["critical_frequencies_mhz"] == [23_420.0]
    payload = call["payload"]
    assert isinstance(payload, ViaStubInput)
    assert payload.frequency_ghz == 5.0
    assert payload.via_positions == [(1.0, 2.0)]
    assert payload.er == 4.0


def test_adapter_handles_empty_selection_without_service_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = importlib.import_module("kicad_mcp.tools.signal_integrity_via_stub")
    service = FakeService()
    server = FastMCP("si-via-stub-empty")
    monkeypatch.setattr(adapter, "_selected_vias", lambda _positions: [])

    adapter.register(
        server,
        adapter.SignalIntegrityViaStubDependencies(service=cast(Any, service)),
    )

    tool = server._tool_manager.list_tools()[0]
    assert tool.fn(5.0, None, 4.0) == "No vias matched the supplied positions on the active board."
    assert service.calls == []


def test_adapter_reports_omitted_vias_to_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = importlib.import_module("kicad_mcp.tools.signal_integrity_via_stub")
    service = FakeService()
    server = FastMCP("si-via-stub-limit")
    vias = [SimpleNamespace(), SimpleNamespace()]
    observation = ViaStubObservation(
        net_name="GND",
        x_mm=1.0,
        y_mm=2.0,
        via_type_name="VT_THROUGH",
        drill_mm=0.3,
        stub_mm=1.6,
    )
    monkeypatch.setattr(adapter, "_selected_vias", lambda _positions: vias)
    monkeypatch.setattr(adapter, "_response_limit", lambda: 1)
    monkeypatch.setattr(adapter, "_board_thickness_mm", lambda: 1.6)
    monkeypatch.setattr(adapter, "_critical_frequencies_mhz", lambda: [])
    monkeypatch.setattr(adapter, "_via_observation", lambda _via: observation)

    adapter.register(
        server,
        adapter.SignalIntegrityViaStubDependencies(service=cast(Any, service)),
    )

    tool = server._tool_manager.list_tools()[0]
    assert tool.fn(5.0, None, 4.0) == "via-result"
    assert service.calls[0]["observations"] == [observation]
    assert service.calls[0]["omitted_observations"] == 1


def test_via_helpers_preserve_defaults_and_type_specific_stub_lengths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = importlib.import_module("kicad_mcp.tools.signal_integrity_via_stub")
    monkeypatch.setattr(adapter, "_stackup_layers", lambda: [])
    assert adapter._board_thickness_mm() == 1.6

    monkeypatch.setattr(adapter, "_board_thickness_mm", lambda: 2.0)
    assert adapter._via_stub_length_mm(SimpleNamespace(type=ViaType.VT_THROUGH)) == 2.0
    assert adapter._via_stub_length_mm(SimpleNamespace(type=ViaType.VT_BLIND_BURIED)) == 1.0
    assert adapter._via_stub_length_mm(SimpleNamespace(type=ViaType.VT_MICRO)) == 0.4


def test_critical_frequencies_fall_back_when_design_intent_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = importlib.import_module("kicad_mcp.tools.signal_integrity_via_stub")
    project = importlib.import_module("kicad_mcp.tools.project")

    def unavailable() -> object:
        raise ValueError("design intent unavailable")

    monkeypatch.setattr(project, "load_design_intent", unavailable)

    assert adapter._critical_frequencies_mhz() == []

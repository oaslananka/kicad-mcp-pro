from __future__ import annotations

import importlib
import inspect
from types import SimpleNamespace
from typing import Any, cast

import pytest
from mcp.server.mcpserver import MCPServer as FastMCP

from kicad_mcp.models.signal_integrity import DecouplingPlacementInput


class FakeService:
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []

    def analyze(
        self,
        payload: object,
        source_x_mm: float,
        source_y_mm: float,
        recommended_mm: float,
        capacitors: list[tuple[str, float, str]],
    ) -> str:
        self.calls.append((payload, source_x_mm, source_y_mm, recommended_mm, capacitors))
        return "decoupling-result"


def test_registration_preserves_signature_docstring_and_delegation() -> None:
    adapter = importlib.import_module("kicad_mcp.tools.signal_integrity_decoupling_placement")
    server = FastMCP("si-decoupling-placement-registration")
    service = FakeService()
    calls: list[tuple[object, ...]] = []

    def anchor(ic_ref: str, power_pin: str) -> tuple[float, float]:
        calls.append(("anchor", ic_ref, power_pin))
        return 10.0, 20.0

    def recommended(freq_mhz: float) -> float:
        calls.append(("recommended", freq_mhz))
        return 2.0

    def capacitors(ic_ref: str, x_mm: float, y_mm: float) -> list[tuple[str, float, str]]:
        calls.append(("capacitors", ic_ref, x_mm, y_mm))
        return [("C1", 1.0, "100nF")]

    adapter.register(
        server,
        adapter.SignalIntegrityDecouplingPlacementDependencies(
            service=cast(Any, service),
            anchor_provider=anchor,
            capacitor_provider=capacitors,
            recommended_distance_provider=recommended,
        ),
    )

    tool_list = server._tool_manager.list_tools()
    assert [tool.name for tool in tool_list] == ["si_calculate_decoupling_placement"]

    tool = tool_list[0]
    assert str(inspect.signature(tool.fn)) == (
        "(ic_ref: 'str', power_pin: 'str', target_freq_mhz: 'float') -> 'str'"
    )
    assert tool.fn.__doc__ == "Estimate decoupling placement quality around an IC power pin."

    assert tool.fn("U1", "7", 250.0) == "decoupling-result"
    assert calls == [
        ("anchor", "U1", "7"),
        ("recommended", 250.0),
        ("capacitors", "U1", 10.0, 20.0),
    ]
    assert len(service.calls) == 1
    payload, x_mm, y_mm, recommended_mm, cap_list = service.calls[0]
    assert isinstance(payload, DecouplingPlacementInput)
    assert payload.ic_ref == "U1"
    assert payload.power_pin == "7"
    assert payload.target_freq_mhz == 250.0
    assert (x_mm, y_mm, recommended_mm) == (10.0, 20.0, 2.0)
    assert cap_list == [("C1", 1.0, "100nF")]


def test_default_dependencies_resolve_helpers_late(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = importlib.import_module("kicad_mcp.tools.signal_integrity_decoupling_placement")
    deps = adapter._default_dependencies()

    monkeypatch.setattr(adapter, "_find_power_anchor", lambda _ic, _pin: (1.0, 2.0))
    monkeypatch.setattr(
        adapter,
        "_nearest_capacitors",
        lambda _ic, _x, _y: [("C9", 0.5, "1uF")],
    )
    monkeypatch.setattr(adapter, "recommended_decoupling_distance_mm", lambda _f: 3.0)

    assert deps.anchor_provider("U1", "1") == (1.0, 2.0)
    assert deps.capacitor_provider("U1", 1.0, 2.0) == [("C9", 0.5, "1uF")]
    assert deps.recommended_distance_provider(100.0) == 3.0


def test_find_power_anchor_prefers_pad_then_falls_back_to_footprint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = importlib.import_module("kicad_mcp.tools.signal_integrity_decoupling_placement")
    board = object()
    footprint = SimpleNamespace(
        reference_field=SimpleNamespace(text=SimpleNamespace(value="U1")),
        value_field=SimpleNamespace(text=SimpleNamespace(value="MCU")),
        position="footprint-position",
    )
    pad = SimpleNamespace(parent=footprint, number="7", position="pad-position")
    monkeypatch.setattr(adapter, "get_board", lambda: board)
    monkeypatch.setattr(
        adapter,
        "point_xy_mm",
        lambda pos: {
            "pad-position": (1.0, 2.0),
            "footprint-position": (3.0, 4.0),
        }[pos],
    )
    monkeypatch.setattr(adapter, "board_pads", lambda _board: [pad])
    monkeypatch.setattr(adapter, "board_footprints", lambda _board: [footprint])

    assert adapter._find_power_anchor("U1", "7") == (1.0, 2.0)

    monkeypatch.setattr(adapter, "board_pads", lambda _board: [])
    assert adapter._find_power_anchor("U1", "99") == (3.0, 4.0)

    monkeypatch.setattr(adapter, "board_footprints", lambda _board: [])
    with pytest.raises(ValueError, match="Footprint 'U2' was not found"):
        adapter._find_power_anchor("U2", "1")


def test_nearest_capacitors_filters_and_sorts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = importlib.import_module("kicad_mcp.tools.signal_integrity_decoupling_placement")
    board = object()

    def footprint(reference: str, value: str, position: str) -> SimpleNamespace:
        return SimpleNamespace(
            reference_field=SimpleNamespace(text=SimpleNamespace(value=reference)),
            value_field=SimpleNamespace(text=SimpleNamespace(value=value)),
            position=position,
        )

    footprints = [
        footprint("U1", "MCU", "u"),
        footprint("R1", "10k", "r"),
        footprint("C2", "1uF", "c2"),
        footprint("C1", "100nF", "c1"),
    ]
    coords = {"u": (0.0, 0.0), "r": (0.5, 0.0), "c2": (2.0, 0.0), "c1": (1.0, 0.0)}
    monkeypatch.setattr(adapter, "get_board", lambda: board)
    monkeypatch.setattr(adapter, "board_footprints", lambda _board: footprints)
    monkeypatch.setattr(adapter, "point_xy_mm", lambda pos: coords[pos])

    assert adapter._nearest_capacitors("U1", 0.0, 0.0) == [
        ("C1", 1.0, "100nF"),
        ("C2", 2.0, "1uF"),
    ]

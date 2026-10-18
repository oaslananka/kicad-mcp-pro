"""Regression tests for collision-safe-by-default net compilation (issue #198).

`sch_build_circuit` used to draw routed Manhattan wires between pins whenever
`auto_layout` was False, which can cross unrelated pins/labels and merge by
geometry into silent shorts. The collision-safe terminal-stub planner must now be
the default for *any* supplied netlist; routed wires must require an explicit
`unsafe_routed_wires=True` opt-in.
"""

from __future__ import annotations

import pytest

from kicad_mcp.models.schematic import AddSymbolInput
from kicad_mcp.tools import schematic as sch

_STATS = {
    "resolved_endpoints": 0,
    "unresolved_endpoints": 0,
    "pin_alias_resolutions": 0,
    "symbol_center_resolutions": 0,
}

_SYMBOLS = [
    {
        "library": "Device",
        "symbol_name": "R",
        "reference": "R1",
        "value": "10k",
        "x_mm": 50.8,
        "y_mm": 50.8,
    }
]
_NETS = [{"name": "SIG", "endpoints": ["R1.1", "R1.2"]}]


@pytest.fixture
def planner_spies(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Record which net planner the builder dispatches to, with no KiCad needed."""
    calls: list[str] = []

    def spy_terminals(symbols, powers, labels, nets, snap):  # type: ignore[no-untyped-def]
        calls.append("terminals")
        return ([], [], [], [], dict(_STATS))

    def spy_wires(symbols, powers, labels, nets, snap):  # type: ignore[no-untyped-def]
        calls.append("wires")
        return ([], [], dict(_STATS))

    monkeypatch.setattr(sch, "_plan_netlist_pin_terminals", spy_terminals)
    monkeypatch.setattr(sch, "_plan_netlist_wires", spy_wires)
    # Isolate from the installed KiCad symbol libraries.
    monkeypatch.setattr(sch, "get_symbol_available_units", lambda *_a, **_k: set())
    return calls


def test_nets_default_to_collision_safe_terminals(planner_spies: list[str]) -> None:
    sch._prepare_build_circuit_inputs(symbols=_SYMBOLS, nets=_NETS)
    assert planner_spies == ["terminals"]


def test_nets_default_to_terminals_even_without_auto_layout(planner_spies: list[str]) -> None:
    # The previous footgun: auto_layout=False used to route Manhattan wires.
    sch._prepare_build_circuit_inputs(symbols=_SYMBOLS, nets=_NETS, auto_layout=False)
    assert planner_spies == ["terminals"]


def test_routed_wires_require_explicit_opt_in(planner_spies: list[str]) -> None:
    sch._prepare_build_circuit_inputs(symbols=_SYMBOLS, nets=_NETS, unsafe_routed_wires=True)
    assert planner_spies == ["wires"]


def test_auto_layout_with_nets_still_uses_terminals(planner_spies: list[str]) -> None:
    sch._prepare_build_circuit_inputs(symbols=_SYMBOLS, nets=_NETS, auto_layout=True)
    assert planner_spies == ["terminals"]


def test_build_circuit_default_keeps_routed_wires_opt_in() -> None:
    # Keyword-only defaults live in __kwdefaults__; routed wires must default off.
    kwdefaults = sch._prepare_build_circuit_inputs.__kwdefaults__ or {}
    assert kwdefaults.get("unsafe_routed_wires") is False


def test_net_compilation_report_announces_routing_mode() -> None:
    safe = sch._render_net_compilation_report(
        symbols=[],
        powers=[],
        labels=[],
        explicit_wires=0,
        nets=[{"name": "SIG"}],
        generated_wires=[],
        unresolved_nets=[],
        resolution_stats=dict(_STATS),
        auto_layout=False,
        terminalized=True,
    )
    assert "terminal labels (collision-safe)" in safe

    unsafe = sch._render_net_compilation_report(
        symbols=[],
        powers=[],
        labels=[],
        explicit_wires=0,
        nets=[{"name": "SIG"}],
        generated_wires=[],
        unresolved_nets=[],
        resolution_stats=dict(_STATS),
        auto_layout=False,
        terminalized=False,
    )
    assert "routed wires (unsafe)" in unsafe


def test_multi_unit_shared_pin_name_alias_does_not_silently_select_unit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A repeated alias on different units must require numeric pin identity."""
    monkeypatch.setattr(
        sch,
        "get_pin_positions",
        lambda _library, _name, x, y, _rotation, unit: {str(unit): (x, y)},
    )
    monkeypatch.setattr(
        sch,
        "get_pin_alias_positions",
        lambda _library, _name, x, y, _rotation, _unit: {"OUT": (x, y)},
    )
    symbols = [
        AddSymbolInput.model_validate(
            {
                "library": "MultiUnit",
                "symbol_name": "DualChild",
                "reference": "U1",
                "value": "DualChild",
                "x_mm": x,
                "y_mm": 50.8,
                "unit": unit,
            }
        )
        for unit, x in ((1, 50.8), (2, 101.6), (3, 152.4))
    ]
    points, aliases, _, _ = sch._netlist_symbol_geometry(symbols, snap_to_grid=True)
    assert set(points["U1"]) == {"1", "2", "3"}
    assert "OUT" not in aliases["U1"]

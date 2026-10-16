"""Benchmarks for the transmission-line impedance calculators and solvers."""

from __future__ import annotations

import pytest

from kicad_mcp.utils.impedance import (
    differential_impedance,
    solve_spacing_for_differential_impedance,
    solve_width_for_impedance,
    trace_impedance,
)

TRACE_TYPES = ["microstrip", "stripline", "coplanar"]


@pytest.mark.parametrize("trace_type", TRACE_TYPES)
def test_trace_impedance_sweep(benchmark, trace_type: str) -> None:
    widths = [0.05 + i * 0.01 for i in range(100)]

    def sweep() -> list[tuple[float, float]]:
        return [trace_impedance(w, 0.2, 4.3, trace_type=trace_type) for w in widths]

    results = benchmark(sweep)
    assert len(results) == len(widths)


@pytest.mark.parametrize("trace_type", TRACE_TYPES)
def test_solve_width_for_50_ohm(benchmark, trace_type: str) -> None:
    width = benchmark(solve_width_for_impedance, 50.0, 0.2, 4.3, trace_type=trace_type)
    assert width > 0


@pytest.mark.parametrize("trace_type", ["microstrip", "stripline"])
def test_solve_spacing_for_90_ohm_differential(benchmark, trace_type: str) -> None:
    spacing = benchmark(
        solve_spacing_for_differential_impedance, 90.0, 0.15, 0.2, 4.3, trace_type=trace_type
    )
    assert spacing > 0


def test_differential_impedance(benchmark) -> None:
    impedance, _er = benchmark(differential_impedance, 0.15, 0.2, 0.2, 4.3)
    assert impedance > 0

"""Regressions for stability formatting and loop-response extraction."""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from kicad_mcp.tools.simulation import _format_stability, _loop_gain_and_phase
from kicad_mcp.utils.ngspice import SimulationResult, SimulationTrace


def test_loop_gain_and_phase_keeps_zero_feedback_and_phase_normalization() -> None:
    gain, phase = _loop_gain_and_phase(
        [10.0, 1.0, 0.5],
        [1.0, 1.0, 0.0],
        [10.0, -180.0, 360.0],
        [0.0, 0.0, 0.0],
    )

    assert gain[:2] == pytest.approx([20.0, 0.0])
    assert math.isinf(gain[-1])
    assert phase == pytest.approx([-350.0, -180.0, 0.0])


def test_format_stability_preserves_crossover_report() -> None:
    result = SimulationResult(
        backend="ngspice-cli",
        analysis="ac",
        netlist_path=Path("loop.cir"),
        x_values=[100.0, 1000.0],
        traces=[
            SimulationTrace("OUT", [10.0, 0.1], [-90.0, -150.0]),
            SimulationTrace("Fb", [1.0, 1.0], [0.0, 0.0]),
        ],
    )
    text = _format_stability(result, "out", "fb")
    assert "- Loop samples: 2" in text
    assert "- Unity-gain crossover:" in text
    assert "- Estimated phase margin:" in text

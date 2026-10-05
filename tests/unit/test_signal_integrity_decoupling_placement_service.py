from __future__ import annotations

import pytest

from kicad_mcp.models.signal_integrity import DecouplingPlacementInput
from kicad_mcp.signal_integrity.decoupling_placement import (
    SignalIntegrityDecouplingPlacementService,
)


@pytest.mark.parametrize(
    ("distance_mm", "expected"),
    [(1.0, "PASS"), (3.0, "WARN"), (5.0, "FAIL")],
)
def test_analyze_preserves_three_level_verdicts(
    distance_mm: float,
    expected: str,
) -> None:
    result = SignalIntegrityDecouplingPlacementService().analyze(
        payload=DecouplingPlacementInput(
            ic_ref="U1",
            power_pin="7",
            target_freq_mhz=250.0,
        ),
        source_x_mm=10.1,
        source_y_mm=10.0,
        recommended_mm=2.0,
        capacitors=[("C1", distance_mm, "100nF")],
    )

    assert result.startswith("Decoupling placement heuristic:\n")
    assert "- IC reference: U1" in result
    assert "- Power pin: 7" in result
    assert "- Anchor position: (10.100, 10.000) mm" in result
    assert "- Target frequency: 250.000 MHz" in result
    assert "- Recommended maximum capacitor distance: 2.000 mm" in result
    assert f"at {distance_mm:.3f} mm ({expected}; PASS <= 2.000 mm" in result
    assert "- C1:" in result
    assert "verify the actual current loop" in result


def test_analyze_preserves_no_capacitor_guidance() -> None:
    result = SignalIntegrityDecouplingPlacementService().analyze(
        payload=DecouplingPlacementInput(
            ic_ref="U1",
            power_pin="1",
            target_freq_mhz=100.0,
        ),
        source_x_mm=1.0,
        source_y_mm=2.0,
        recommended_mm=5.0,
        capacitors=[],
    )

    assert "- No capacitor footprints were found on the active board." in result
    assert "- Add a local decoupler as close as possible to the selected power pin." in result
    assert "Nearest capacitors:" not in result


def test_analyze_preserves_value_unknown_and_five_cap_limit() -> None:
    capacitors = [(f"C{i}", float(i), "" if i == 1 else "100nF") for i in range(1, 7)]

    result = SignalIntegrityDecouplingPlacementService().analyze(
        payload=DecouplingPlacementInput(
            ic_ref="U2",
            power_pin="3",
            target_freq_mhz=500.0,
        ),
        source_x_mm=0.0,
        source_y_mm=0.0,
        recommended_mm=1.0,
        capacitors=capacitors,
    )

    assert "Nearest decoupler: C1 (value unknown)" in result
    assert "- C5:" in result
    assert "- C6:" not in result

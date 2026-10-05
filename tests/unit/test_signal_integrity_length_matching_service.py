from __future__ import annotations

import pytest

from kicad_mcp.signal_integrity.length_matching import SignalIntegrityLengthMatchingService


@pytest.mark.parametrize(
    ("spread_mm", "expected"),
    [(1.0, "PASS"), (3.0, "WARN"), (5.0, "FAIL")],
)
def test_validate_preserves_three_level_verdicts(spread_mm: float, expected: str) -> None:
    result = SignalIntegrityLengthMatchingService().validate(
        net_groups=[["A", "B"]],
        tolerance_mm=2.0,
        lengths={"A": 10.0, "B": 10.0 + spread_mm},
    )

    assert f"Group 1 ({expected})" in result
    assert f"spread={spread_mm:.3f} mm" in result


def test_validate_preserves_empty_and_missing_group_reporting() -> None:
    result = SignalIntegrityLengthMatchingService().validate(
        net_groups=[[], ["MISSING"], ["A", "", "B"]],
        tolerance_mm=1.0,
        lengths={"A": 10.0, "B": 10.5},
    )

    assert result.startswith(
        "Length-matching validation (tolerance 1.000 mm; "
        "PASS <= 1.000 mm, WARN <= 2.000 mm, FAIL > 2.000 mm):"
    )
    assert "- Group 1: skipped empty group" in result
    assert "- Group 2: missing routed tracks for MISSING" in result
    assert "- Group 3 (PASS): shortest A=10.000 mm, longest B=10.500 mm, spread=0.500 mm" in result

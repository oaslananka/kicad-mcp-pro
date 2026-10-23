"""Preserve the engineering-facing output conventions of stackup synthesis."""

from __future__ import annotations

import pytest

from kicad_mcp.signal_integrity.stackup_synthesis import (
    _impedance_summary_suffix,
    _stackup_layer_count,
)


@pytest.mark.parametrize(
    ("impedance", "differential", "expected"),
    [
        (90, True, ", 90ohm diff"),
        (50, False, ", 50ohm SE"),
        (0, True, ""),
        (None, False, ""),
        ("100", True, ", 100ohm diff"),
        (-1, False, ", -1ohm SE"),
    ],
)
def test_impedance_suffix_preserves_truthiness_contract(
    impedance: object, differential: bool, expected: str
) -> None:
    assert _impedance_summary_suffix(impedance, differential) == expected


@pytest.mark.parametrize(
    ("freq", "differential", "highspeed", "layers"),
    [
        (0.0, False, False, 2),
        (0.5, True, False, 4),
        (0.9, False, True, 4),
        (1.0, True, True, 6),
        (4.999, False, True, 6),
        (5.0, True, True, 8),
        (6.0, False, False, 2),
    ],
)
def test_layer_selection_preserves_existing_fallbacks(
    freq: float, differential: bool, highspeed: bool, layers: int
) -> None:
    assert _stackup_layer_count(freq, differential, highspeed) == layers

"""Unit conversion helpers."""

from __future__ import annotations


def mm_to_nm(mm_value: float) -> int:
    """Convert millimeters to nanometers."""
    return int(round(mm_value * 1_000_000))


def nm_to_mm(nm_value: int) -> float:
    """Convert nanometers to millimeters."""
    return nm_value / 1_000_000


def mil_to_mm(mil_value: float) -> float:
    """Convert mils to millimeters."""
    return mil_value * 0.0254


def mm_to_mil(mm_value: float) -> float:
    """Convert millimeters to mils."""
    return mm_value / 0.0254

"""Unit conversion helpers."""

from __future__ import annotations


def _coord_nm(point: object, axis: str) -> int:
    """Read either ``x_nm``/``y_nm`` or ``x``/``y`` coordinates as nanometers."""
    attr_name = f"{axis}_nm"
    value = getattr(point, attr_name) if hasattr(point, attr_name) else getattr(point, axis)
    return int(value)


def mm_to_nm(mm_value: float) -> int:
    """Convert millimeters to nanometers."""
    return int(round(mm_value * 1_000_000))


def nm_to_mm(nm_value: float) -> float:
    """Convert nanometers to millimeters.

    Accepts ``float`` as well as ``int`` because the KiCad IPC API reports some
    derived lengths that way -- ``Track.length()`` and ``ArcTrack.length()``
    both return ``float`` nanometers. Widening the parameter keeps every
    existing ``Callable[[int], float]`` caller assignable.
    """
    return nm_value / 1_000_000


def mil_to_mm(mil_value: float) -> float:
    """Convert mils to millimeters."""
    return mil_value * 0.0254


def mm_to_mil(mm_value: float) -> float:
    """Convert millimeters to mils."""
    return mm_value / 0.0254

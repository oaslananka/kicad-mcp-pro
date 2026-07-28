"""Footprint transform helpers shared by live PCB mutation tools."""

from __future__ import annotations

import math
from typing import Literal

from kipy.geometry import Angle

RotationAttribute = Literal["angle", "orientation"]
_SUPPORTED_ROTATION_ATTRIBUTES: tuple[RotationAttribute, ...] = ("angle", "orientation")


class FootprintRotationError(RuntimeError):
    """Raised when a requested footprint rotation cannot be applied or verified."""


def _rotation_degrees(value: object) -> float:
    if isinstance(value, Angle):
        return float(value.degrees)
    if isinstance(value, int | float) and not isinstance(value, bool):
        return float(value)
    degrees = getattr(value, "degrees", None)
    if isinstance(degrees, int | float) and not isinstance(degrees, bool):
        return float(degrees)
    raise FootprintRotationError("Footprint rotation value does not expose numeric degrees.")


def apply_footprint_rotation(footprint: object, rotation_deg: float) -> RotationAttribute:
    """Assign a KiCad ``Angle`` through the first writable rotation surface."""
    if not math.isfinite(rotation_deg):
        raise FootprintRotationError("Requested footprint rotation must be finite.")

    requested = Angle.from_degrees(rotation_deg)
    available: list[RotationAttribute] = []
    failures: list[str] = []
    for attribute in _SUPPORTED_ROTATION_ATTRIBUTES:
        try:
            getattr(footprint, attribute)
        except AttributeError:
            continue
        available.append(attribute)
        try:
            setattr(footprint, attribute, requested)
        except Exception as exc:  # KiCad IPC surfaces raise generated transport/type errors.
            failures.append(f"{attribute}: {type(exc).__name__}")
            continue
        return attribute

    if not available:
        raise FootprintRotationError(
            "Footprint does not expose a supported angle or orientation surface."
        )
    detail = ", ".join(failures) if failures else ", ".join(available)
    raise FootprintRotationError(f"Requested footprint rotation could not be applied ({detail}).")


def verify_footprint_rotation(
    footprint: object,
    attribute: RotationAttribute,
    requested_deg: float,
    *,
    tolerance_deg: float = 1e-3,
) -> float:
    """Read back and verify a footprint rotation using wrapped angular distance."""
    try:
        actual = _rotation_degrees(getattr(footprint, attribute))
    except AttributeError as exc:
        raise FootprintRotationError(
            f"Footprint rotation verification failed: '{attribute}' is unavailable."
        ) from exc

    delta = (actual - requested_deg + 180.0) % 360.0 - 180.0
    if abs(delta) > tolerance_deg:
        raise FootprintRotationError(
            "Footprint rotation verification failed: "
            f"requested {requested_deg:.6f} degrees, observed {actual:.6f} degrees."
        )
    return actual

"""Typed geometry helpers for KiCad PCB segment objects.

The canonical track-length contract uses explicit ``start`` and ``end`` point
coordinates expressed in nanometres (either ``x_nm``/``y_nm`` or KiCad-native
``x``/``y`` attributes). It intentionally models straight track segments only;
curved and polyline geometry require a separately named domain-specific helper.
"""

from __future__ import annotations

import math
from typing import Protocol, cast

from ..utils.units import _coord_nm, nm_to_mm


class SegmentTrack(Protocol):
    """Straight PCB track subset required for length calculation."""

    start: object
    end: object


class BoardGeometryError(ValueError):
    """Raised when a supported PCB geometry object cannot be read."""


def point_xy_mm(point: object) -> tuple[float, float]:
    """Return one KiCad point as ``(x_mm, y_mm)``.

    Supported point shapes expose either ``x_nm``/``y_nm`` or KiCad-native
    ``x``/``y`` nanometre attributes. Malformed coordinates fail explicitly.
    """
    try:
        return (
            nm_to_mm(_coord_nm(point, "x")),
            nm_to_mm(_coord_nm(point, "y")),
        )
    except (AttributeError, OverflowError, TypeError, ValueError) as exc:
        raise BoardGeometryError(f"Could not read point geometry: {exc}") from exc


def track_segment_length_mm(track: object) -> float:
    """Return straight-line ``start``/``end`` track length in millimetres.

    No KiCad-provided cached length field is used: explicit endpoints are the
    stable compatibility source across supported board API shapes.
    """
    try:
        segment = cast(SegmentTrack, track)
        dx_mm = nm_to_mm(_coord_nm(segment.end, "x") - _coord_nm(segment.start, "x"))
        dy_mm = nm_to_mm(_coord_nm(segment.end, "y") - _coord_nm(segment.start, "y"))
    except (AttributeError, OverflowError, TypeError, ValueError) as exc:
        raise BoardGeometryError(f"Could not read segment track start/end geometry: {exc}") from exc
    return math.hypot(dx_mm, dy_mm)

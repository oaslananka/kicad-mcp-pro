"""Strict straight differential-pair geometry gate for provisional native routes.

This only handles two parallel, aligned, same-layer tracks. It deliberately
refuses curved, meandering, multi-segment, via or impedance requirements.
Real custom KiCad DRC and physical stackup review remain separate gates.
"""

from __future__ import annotations

from math import hypot, isfinite

from .differential_pair_rules import infer_diff_pair_base
from .manual_tracks import TrackSpec
from .path_planner import RoutePlanningError


def inspect_straight_pair(
    plus: TrackSpec,
    minus: TrackSpec,
    *,
    gap_mm: float,
    max_skew_mm: float,
) -> dict[str, float]:
    """Reject two tracks unless exactly parallel, gap-matched and length-matched."""
    values = (
        plus.x1_mm,
        plus.y1_mm,
        plus.x2_mm,
        plus.y2_mm,
        plus.width_mm,
        minus.x1_mm,
        minus.y1_mm,
        minus.x2_mm,
        minus.y2_mm,
        minus.width_mm,
        gap_mm,
        max_skew_mm,
    )
    if not all(isfinite(value) for value in values) or not (
        0 < gap_mm <= 5 and 0 <= max_skew_mm <= 5
    ):
        raise RoutePlanningError("Invalid differential pair dimensions")
    if plus.layer != minus.layer or not plus.layer.endswith("_Cu"):
        raise RoutePlanningError("Differential pair requires the same copper layer")
    if plus.width_mm != minus.width_mm or plus.width_mm <= 0:
        raise RoutePlanningError("Differential pair track widths must match")
    if not infer_diff_pair_base(plus.net_name, minus.net_name):
        raise RoutePlanningError("Differential pair requires matching positive/negative net names")

    px = plus.x2_mm - plus.x1_mm
    py = plus.y2_mm - plus.y1_mm
    nx = minus.x2_mm - minus.x1_mm
    ny = minus.y2_mm - minus.y1_mm
    plen = hypot(px, py)
    nlen = hypot(nx, ny)
    if plen <= 0 or nlen <= 0:
        raise RoutePlanningError("Differential pair has zero-length copper")
    if px * nx + py * ny <= 0:
        raise RoutePlanningError("Differential pair track direction must match")
    if abs(px * ny - py * nx) > 1e-5:
        raise RoutePlanningError("Differential pair tracks must be parallel")
    if abs(plen - nlen) > max_skew_mm + 1e-6:
        raise RoutePlanningError("Differential pair length skew exceeds the limit")

    start_delta = (minus.x1_mm - plus.x1_mm, minus.y1_mm - plus.y1_mm)
    end_delta = (minus.x2_mm - plus.x2_mm, minus.y2_mm - plus.y2_mm)
    if hypot(start_delta[0] - end_delta[0], start_delta[1] - end_delta[1]) > 0.001:
        raise RoutePlanningError("Differential pair must keep aligned parallel spacing")
    if abs(start_delta[0] * px + start_delta[1] * py) > plen * 0.001:
        raise RoutePlanningError("Differential pair endpoints are not laterally aligned")
    copper_gap = abs(px * start_delta[1] - py * start_delta[0]) / plen - plus.width_mm
    if abs(copper_gap - gap_mm) > 0.001:
        raise RoutePlanningError("Differential pair copper gap does not match the rule")
    return {
        "gapMm": round(copper_gap, 6),
        "lengthPlusMm": round(plen, 6),
        "lengthMinusMm": round(nlen, 6),
        "skewMm": round(abs(plen - nlen), 6),
    }

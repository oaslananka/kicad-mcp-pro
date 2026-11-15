"""Bounded front/back, one-through-via candidate for real native DRC.

Only collinear, horizontal/vertical SMD pads on opposite outer layers.
This does NOT cover inner layers, differential pairs, zones or curved routes.
"""

from __future__ import annotations

from math import hypot, isfinite

from .manual_tracks import TrackSpec, ViaSpec
from .path_planner import Obstacle, RoutePlanningError, _segment_clear

type Point = tuple[float, float]


def plan_one_through_via(
    start: Point,
    end: Point,
    *,
    front_obstacles: tuple[Obstacle, ...],
    back_obstacles: tuple[Obstacle, ...],
    start_layer: str,
    end_layer: str,
    net_name: str,
    width_mm: float,
    clearance_mm: float,
    diameter_mm: float,
    drill_mm: float,
) -> tuple[list[TrackSpec], ViaSpec, dict[str, float | int]]:
    """Pick the cheapest of five deterministic, obstacle-screened via sites."""
    if (start_layer, end_layer) not in (("F_Cu", "B_Cu"), ("B_Cu", "F_Cu")):
        raise RoutePlanningError("One through via supports only opposite outer copper layers")
    if not net_name or not all(
        isfinite(x) for x in (*start, *end, width_mm, clearance_mm, diameter_mm, drill_mm)
    ):
        raise RoutePlanningError("Invalid net or non-finite via dimensions")
    if not (
        0 < width_mm <= 5
        and 0 <= clearance_mm <= 5
        and 0.4 <= diameter_mm <= 5
        and 0.2 <= drill_mm <= diameter_mm - 0.2
        and width_mm <= diameter_mm
    ):
        raise RoutePlanningError("Unsafe one-through-via diameter/drill/clearance")
    dx, dy = end[0] - start[0], end[1] - start[1]
    distance = hypot(dx, dy)
    if distance < 2 or distance > 80:
        raise RoutePlanningError("Via route length is outside bounded extent")
    if abs(dx) > 1e-6 and abs(dy) > 1e-6:
        raise RoutePlanningError("One-via route requires aligned horizontal/vertical pads")
    first_obstacles = front_obstacles if start_layer == "F_Cu" else back_obstacles
    last_obstacles = back_obstacles if end_layer == "B_Cu" else front_obstacles
    candidates: list[tuple[float, float, list[TrackSpec], ViaSpec]] = []
    for fraction in (0.5, 0.35, 0.65, 0.25, 0.75):
        point = (round(start[0] + dx * fraction, 6), round(start[1] + dy * fraction, 6))
        via = ViaSpec(*point, diameter_mm, drill_mm, net_name)
        pad_radius = diameter_mm / 2 + clearance_mm
        if any(
            not _segment_clear(point, point, obstacles, pad_radius)
            for obstacles in (front_obstacles, back_obstacles)
        ):
            continue
        if not _segment_clear(start, point, first_obstacles, width_mm / 2 + clearance_mm):
            continue
        if not _segment_clear(point, end, last_obstacles, width_mm / 2 + clearance_mm):
            continue
        if hypot(start[0] - point[0], start[1] - point[1]) < 0.1 or (
            hypot(end[0] - point[0], end[1] - point[1]) < 0.1
        ):
            continue
        tracks = [
            TrackSpec(*start, *point, start_layer, width_mm, net_name),
            TrackSpec(*point, *end, end_layer, width_mm, net_name),
        ]
        # Via penalty is a routing preference only, never proof of economics.
        via_cost_mm = 5.0
        candidate_cost = distance + via_cost_mm
        candidates.append((candidate_cost, abs(fraction - 0.5), tracks, via))
    if not candidates:
        raise RoutePlanningError("No collision-free one-via transition is available")
    best = min(candidates, key=lambda entry: (entry[0], entry[1], entry[3].x_mm, entry[3].y_mm))
    return (
        best[2],
        best[3],
        {
            "viaCount": 1,
            "viaCostMm": 5.0,
            "totalTraceLengthMm": round(distance, 6),
            "estimatedPathCostMm": round(best[0], 6),
        },
    )

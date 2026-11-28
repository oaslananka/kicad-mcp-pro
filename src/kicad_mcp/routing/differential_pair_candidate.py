"""Strict straight differential-pair geometry gate for provisional native routes.

This only handles two parallel, aligned, same-layer tracks. It deliberately
refuses curved, meandering, multi-segment, via or impedance requirements.
Real custom KiCad DRC and physical stackup review remain separate gates.
"""

from __future__ import annotations

from math import hypot, isfinite

from .differential_pair_rules import PAIR_NAME_GUIDANCE, infer_diff_pair_base
from .manual_tracks import TrackSpec
from .path_planner import (
    Obstacle,
    RoutePlanningError,
    _distance_between_segments,
    _segment_clear,
    _simplify,
    plan_hv45_path,
)


def _validate_pair_scope(
    plus: TrackSpec,
    minus: TrackSpec,
    *,
    gap_mm: float,
    max_skew_mm: float,
) -> None:
    """Validate net, layer and rule dimensions before geometry analysis."""
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
        raise RoutePlanningError(PAIR_NAME_GUIDANCE)


def inspect_straight_pair(
    plus: TrackSpec,
    minus: TrackSpec,
    *,
    gap_mm: float,
    max_skew_mm: float,
) -> dict[str, float]:
    """Reject two tracks unless exactly parallel, gap-matched and length-matched."""
    _validate_pair_scope(plus, minus, gap_mm=gap_mm, max_skew_mm=max_skew_mm)

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


type Point = tuple[float, float]


def _coupled_axis(
    plus_start: Point,
    plus_end: Point,
    minus_start: Point,
    minus_end: Point,
    separation: float,
) -> tuple[Point, Point, Point, float]:
    coords = (*plus_start, *plus_end, *minus_start, *minus_end)
    if not all(isfinite(value) for value in coords):
        raise RoutePlanningError("Non-finite pair pad locations")
    mid_start: Point = (
        (plus_start[0] + minus_start[0]) / 2,
        (plus_start[1] + minus_start[1]) / 2,
    )
    mid_end: Point = (
        (plus_end[0] + minus_end[0]) / 2,
        (plus_end[1] + minus_end[1]) / 2,
    )
    dx = mid_end[0] - mid_start[0]
    dy = mid_end[1] - mid_start[1]
    distance = hypot(dx, dy)
    if distance < 2.0 or min(abs(dx), abs(dy)) > 1e-6:
        raise RoutePlanningError("Coupled pair requires horizontally or vertically aligned pads")
    along = (dx / distance, dy / distance)
    normal = (-along[1], along[0])
    minus_shift = (minus_start[0] - plus_start[0], minus_start[1] - plus_start[1])
    minus_end_shift = (minus_end[0] - plus_end[0], minus_end[1] - plus_end[1])
    if (
        abs(hypot(*minus_shift) - separation) > 1e-4
        or hypot(minus_shift[0] - minus_end_shift[0], minus_shift[1] - minus_end_shift[1]) > 1e-4
        or abs(minus_shift[0] * along[0] + minus_shift[1] * along[1]) > 1e-4
    ):
        raise RoutePlanningError("Coupled pair endpoint spacing/offset is not aligned")
    plus_side = (
        1.0
        if ((plus_start[0] - mid_start[0]) * normal[0] + (plus_start[1] - mid_start[1]) * normal[1])
        > 0
        else -1.0
    )
    return mid_start, mid_end, along, plus_side


def _miter_offset(points: tuple[Point, ...], signed_distance: float) -> tuple[Point, ...]:
    directions: list[Point] = []
    normals: list[Point] = []
    for a, b in zip(points, points[1:], strict=False):
        dx, dy = b[0] - a[0], b[1] - a[1]
        length = hypot(dx, dy)
        if length < 1e-6:
            raise RoutePlanningError("Coupled pair contains zero-length segment")
        unit = (dx / length, dy / length)
        directions.append(unit)
        normals.append((-unit[1], unit[0]))
    output = []
    for index, point in enumerate(points):
        if index == 0:
            v = normals[0]
        elif index == len(points) - 1:
            v = normals[-1]
        else:
            a, b = normals[index - 1], normals[index]
            d0, d1 = directions[index - 1], directions[index]
            denominator = 1 + d0[0] * d1[0] + d0[1] * d1[1]
            if denominator <= 0.3:
                raise RoutePlanningError("Coupled pair has an unsafe sharp return")
            v = ((a[0] + b[0]) / denominator, (a[1] + b[1]) / denominator)
        output.append(
            (
                round(point[0] + signed_distance * v[0], 6),
                round(point[1] + signed_distance * v[1], 6),
            )
        )
    return tuple(output)


def _segments_from_points(
    points: tuple[Point, ...],
    layer: str,
    width: float,
    net: str,
) -> tuple[TrackSpec, ...]:
    tracks: list[TrackSpec] = []
    for a, b in zip(points, points[1:], strict=False):
        dx, dy = abs(b[0] - a[0]), abs(b[1] - a[1])
        if dx + dy <= 1e-6 or not (dx <= 2e-6 or dy <= 2e-6 or abs(dx - dy) <= 2e-6):
            raise RoutePlanningError("Coupled pair offset broke H/V/45 copper geometry")
        tracks.append(TrackSpec(*a, *b, layer, width, net))
    if not 1 <= len(tracks) <= 64:
        raise RoutePlanningError("Coupled route exceeds bounded track count")
    return tuple(tracks)


def _validate_coupled_clearance(
    plus: tuple[TrackSpec, ...],
    minus: tuple[TrackSpec, ...],
    obstacles: tuple[Obstacle, ...],
    width: float,
    gap: float,
    clearance: float,
) -> float:
    def endpoints(track: TrackSpec) -> tuple[Point, Point]:
        return (track.x1_mm, track.y1_mm), (track.x2_mm, track.y2_mm)

    for lane in (plus, minus):
        for index, track in enumerate(lane):
            a, b = endpoints(track)
            if not _segment_clear(a, b, obstacles, width / 2 + clearance):
                raise RoutePlanningError("Coupled copper route collides with an obstacle")
            for other in lane[index + 2 :]:
                c, d = endpoints(other)
                if _distance_between_segments(a, b, c, d) < 1e-6:
                    raise RoutePlanningError("Coupled copper lane crosses itself")
    closest = min(
        _distance_between_segments(*endpoints(p), *endpoints(n)) for p in plus for n in minus
    )
    if closest + 2e-5 < width + gap:
        raise RoutePlanningError("Coupled pair copper gap is smaller than the requested rule")
    return closest - width


def _eligible_horizontal_fanout(
    plus_start: Point,
    plus_end: Point,
    minus_start: Point,
    minus_end: Point,
    separation: float,
) -> bool:
    """Only a short, same-direction, same-layer horizontal USB-style fanout."""
    coords = (*plus_start, *plus_end, *minus_start, *minus_end)
    if not all(isfinite(v) for v in coords):
        return False
    if (
        abs(plus_start[0] - minus_start[0]) > 1e-4
        or abs(plus_end[0] - minus_end[0]) > 1e-4
        or not 2.5 <= abs(plus_end[0] - plus_start[0]) <= 15
        or abs(plus_end[1] - plus_start[1]) > 0.1
        or abs(minus_end[1] - minus_start[1]) > 0.1
    ):
        return False
    start_offset = minus_start[1] - plus_start[1]
    end_offset = minus_end[1] - plus_end[1]
    return (
        start_offset * end_offset > 0
        and separation + 0.05 <= min(abs(start_offset), abs(end_offset))
        and max(abs(start_offset), abs(end_offset)) <= separation + 0.6
        and abs(abs(start_offset) - abs(end_offset)) <= 0.1
    )


def _plan_horizontal_fanout(
    plus_start: Point,
    plus_end: Point,
    minus_start: Point,
    minus_end: Point,
    obstacles: tuple[Obstacle, ...],
    layer: str,
    net_plus: str,
    net_minus: str,
    width_mm: float,
    gap_mm: float,
    clearance_mm: float,
    max_skew_mm: float,
) -> tuple[tuple[TrackSpec, ...], tuple[TrackSpec, ...], dict[str, float]]:
    """Bounded symmetric H/45/H/45/H breakout, never a free-form router.

    Only independently reviewed native DRC may authorize a later write.
    """
    spacing = width_mm + gap_mm
    side = 1 if minus_start[1] > plus_start[1] else -1
    center_y = (plus_start[1] + minus_start[1] + plus_end[1] + minus_end[1]) / 4
    lead = 0.2
    direction = 1 if plus_end[0] > plus_start[0] else -1

    def lane(start: Point, end: Point, middle_y: float, net: str) -> tuple[TrackSpec, ...]:
        departure = abs(middle_y - start[1])
        arrival = abs(end[1] - middle_y)
        if min(departure, arrival) < 0.01 or max(departure, arrival) > 0.5:
            raise RoutePlanningError("Fanout exceeds bounded 45-degree departure limits")
        x1 = start[0] + direction * lead
        x2 = x1 + direction * departure
        x4 = end[0] - direction * lead
        x3 = x4 - direction * arrival
        if direction * (x3 - x2) < 0.5:
            raise RoutePlanningError("Not enough room for a coupled fanout center section")
        points = tuple(
            (round(x, 6), round(y, 6))
            for x, y in (
                start,
                (x1, start[1]),
                (x2, middle_y),
                (x3, middle_y),
                (x4, end[1]),
                end,
            )
        )
        return _segments_from_points(points, layer, width_mm, net)

    plus = lane(plus_start, plus_end, center_y - side * spacing / 2, net_plus)
    minus = lane(minus_start, minus_end, center_y + side * spacing / 2, net_minus)
    min_gap = _validate_coupled_clearance(plus, minus, obstacles, width_mm, gap_mm, clearance_mm)
    length_p = sum(hypot(t.x2_mm - t.x1_mm, t.y2_mm - t.y1_mm) for t in plus)
    length_n = sum(hypot(t.x2_mm - t.x1_mm, t.y2_mm - t.y1_mm) for t in minus)
    skew = abs(length_p - length_n)
    if skew > max_skew_mm + 1e-5:
        raise RoutePlanningError("Fanout pair length difference exceeds skew budget")
    return (
        plus,
        minus,
        {
            "lengthPlusMm": round(length_p, 6),
            "lengthMinusMm": round(length_n, 6),
            "skewMm": round(skew, 6),
            "minCopperGapMm": round(min_gap, 6),
        },
    )


def plan_coupled_hv45_pair(
    *,
    plus_start: Point,
    plus_end: Point,
    minus_start: Point,
    minus_end: Point,
    obstacles: tuple[Obstacle, ...],
    layer: str,
    net_plus: str,
    net_minus: str,
    width_mm: float,
    gap_mm: float,
    clearance_mm: float,
    max_skew_mm: float,
) -> tuple[tuple[TrackSpec, ...], tuple[TrackSpec, ...], dict[str, float]]:
    """Plan one bounded shared centerline and two geometrically matched lanes.

    The native KiCad DRC preflight remains mandatory before writing copper.
    """
    if not infer_diff_pair_base(net_plus, net_minus):
        raise RoutePlanningError("Coupled pair requires matched P/N nets. " + PAIR_NAME_GUIDANCE)
    if not layer.endswith("_Cu"):
        raise RoutePlanningError("Coupled pair requires a copper layer")
    if not all(isfinite(x) for x in (width_mm, gap_mm, clearance_mm, max_skew_mm)):
        raise RoutePlanningError("Non-finite differential pair dimensions")
    if not 0 < width_mm <= 5 or not 0 < gap_mm <= 5 or not 0 <= clearance_mm <= 5:
        raise RoutePlanningError("Invalid differential copper dimensions")
    if not 0 <= max_skew_mm <= 5:
        raise RoutePlanningError("Invalid differential pair skew budget")
    separation = width_mm + gap_mm
    if _eligible_horizontal_fanout(plus_start, plus_end, minus_start, minus_end, separation):
        return _plan_horizontal_fanout(
            plus_start,
            plus_end,
            minus_start,
            minus_end,
            obstacles,
            layer,
            net_plus,
            net_minus,
            width_mm,
            gap_mm,
            clearance_mm,
            max_skew_mm,
        )
    start, end, along, side = _coupled_axis(
        plus_start, plus_end, minus_start, minus_end, separation
    )
    length = hypot(end[0] - start[0], end[1] - start[1])
    lead = min(0.8, 0.18 * length)
    departure = (start[0] + lead * along[0], start[1] + lead * along[1])
    arrival = (end[0] - lead * along[0], end[1] - lead * along[1])
    mid = plan_hv45_path(
        departure,
        arrival,
        obstacles,
        track_width_mm=2 * width_mm + gap_mm,
        clearance_mm=clearance_mm,
    )
    centerline = _simplify((start, *mid, end))
    # The centerline must leave and approach the paired pad pair straight.
    first = centerline[1][0] - start[0], centerline[1][1] - start[1]
    last = end[0] - centerline[-2][0], end[1] - centerline[-2][1]
    if (
        first[0] * along[0] + first[1] * along[1] < 0.1
        or (abs(first[0] * along[1] - first[1] * along[0]) > 1e-6)
        or last[0] * along[0] + last[1] * along[1] < 0.1
        or (abs(last[0] * along[1] - last[1] * along[0]) > 1e-6)
    ):
        raise RoutePlanningError("Coupled pair departure/arrival tangent is not aligned")
    plus_points = _miter_offset(centerline, side * separation / 2)
    minus_points = _miter_offset(centerline, -side * separation / 2)
    for expected, actual in (
        (plus_start, plus_points[0]),
        (plus_end, plus_points[-1]),
        (minus_start, minus_points[0]),
        (minus_end, minus_points[-1]),
    ):
        if hypot(actual[0] - expected[0], actual[1] - expected[1]) > 0.0001:
            raise RoutePlanningError("Coupled pair offset does not reach the actual pads")
    plus = _segments_from_points(plus_points, layer, width_mm, net_plus)
    minus = _segments_from_points(minus_points, layer, width_mm, net_minus)
    min_gap = _validate_coupled_clearance(plus, minus, obstacles, width_mm, gap_mm, clearance_mm)
    length_p = sum(hypot(t.x2_mm - t.x1_mm, t.y2_mm - t.y1_mm) for t in plus)
    length_n = sum(hypot(t.x2_mm - t.x1_mm, t.y2_mm - t.y1_mm) for t in minus)
    skew = abs(length_p - length_n)
    if skew > max_skew_mm + 1e-5:
        raise RoutePlanningError("Coupled pair length difference exceeds skew budget")
    if len(plus) + len(minus) > 128:
        raise RoutePlanningError("Too many coupled differential segments")
    return (
        plus,
        minus,
        {
            "lengthPlusMm": round(length_p, 6),
            "lengthMinusMm": round(length_n, 6),
            "skewMm": round(skew, 6),
            "minCopperGapMm": round(min_gap, 6),
        },
    )

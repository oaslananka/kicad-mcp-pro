"""Deterministic, bounded H/V/45 copper-centerline planning.

This planner operates on explicitly supplied conservative obstacle envelopes.
It is NOT a substitute for full KiCad DRC or native interactive shove routing.
Callers must reject incomplete board geometry and verify any saved result with
independent native DRC before calling a design complete.
"""

from __future__ import annotations

from dataclasses import dataclass
from heapq import heappop, heappush
from math import ceil, floor, hypot, isfinite, sqrt

type Point = tuple[float, float]
_EPS = 1e-8


class RoutePlanningError(ValueError):
    """No verified candidate path could be found within planning limits."""


@dataclass(frozen=True)
class CircleObstacle:
    x_mm: float
    y_mm: float
    radius_mm: float


@dataclass(frozen=True)
class SegmentObstacle:
    x1_mm: float
    y1_mm: float
    x2_mm: float
    y2_mm: float
    radius_mm: float


type Obstacle = CircleObstacle | SegmentObstacle


def _distance_to_segment(point: Point, a: Point, b: Point) -> float:
    dx, dy = b[0] - a[0], b[1] - a[1]
    length_squared = dx * dx + dy * dy
    if length_squared <= _EPS * _EPS:
        return hypot(point[0] - a[0], point[1] - a[1])
    t = max(0.0, min(1.0, ((point[0] - a[0]) * dx + (point[1] - a[1]) * dy) / length_squared))
    return hypot(point[0] - (a[0] + t * dx), point[1] - (a[1] + t * dy))


def _cross(a: Point, b: Point, c: Point) -> float:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _intersects(a: Point, b: Point, c: Point, d: Point) -> bool:
    ab1, ab2 = _cross(a, b, c), _cross(a, b, d)
    cd1, cd2 = _cross(c, d, a), _cross(c, d, b)
    return (
        ab1 * ab2 <= _EPS
        and cd1 * cd2 <= _EPS
        and min(a[0], b[0]) <= max(c[0], d[0]) + _EPS
        and min(c[0], d[0]) <= max(a[0], b[0]) + _EPS
        and min(a[1], b[1]) <= max(c[1], d[1]) + _EPS
        and min(c[1], d[1]) <= max(a[1], b[1]) + _EPS
    )


def _distance_between_segments(a: Point, b: Point, c: Point, d: Point) -> float:
    if _intersects(a, b, c, d):
        return 0.0
    return min(
        _distance_to_segment(a, c, d),
        _distance_to_segment(b, c, d),
        _distance_to_segment(c, a, b),
        _distance_to_segment(d, a, b),
    )


def _segment_clear(
    a: Point,
    b: Point,
    obstacles: tuple[Obstacle, ...],
    envelope_mm: float,
) -> bool:
    for obstacle in obstacles:
        if isinstance(obstacle, CircleObstacle):
            distance = _distance_to_segment((obstacle.x_mm, obstacle.y_mm), a, b)
        else:
            distance = _distance_between_segments(
                a,
                b,
                (obstacle.x1_mm, obstacle.y1_mm),
                (obstacle.x2_mm, obstacle.y2_mm),
            )
        if distance + _EPS < obstacle.radius_mm + envelope_mm:
            return False
    return True


def _hv45(a: Point, b: Point) -> bool:
    dx, dy = abs(a[0] - b[0]), abs(a[1] - b[1])
    return dx + dy > _EPS and (dx < _EPS or dy < _EPS or abs(dx - dy) < _EPS)


def is_hv45_path(path: tuple[Point, ...]) -> bool:
    """Check all segments are nonzero H, V or exactly 45 degrees."""
    return len(path) >= 2 and all(_hv45(a, b) for a, b in zip(path, path[1:], strict=False))


def _simplify(points: tuple[Point, ...]) -> tuple[Point, ...]:
    if len(points) < 3:
        return points
    compact: list[Point] = [points[0]]
    for point in points[1:]:
        if point == compact[-1]:
            continue
        compact.append(point)
        while len(compact) >= 3:
            a, b, c = compact[-3:]
            if abs(_cross(a, b, c)) >= _EPS:
                break
            compact.pop(-2)
    return tuple(compact)


def _terminal_candidates(a: Point, end: Point) -> tuple[tuple[Point, ...], ...]:
    dx, dy = end[0] - a[0], end[1] - a[1]
    delta = min(abs(dx), abs(dy))
    sx = 1 if dx >= 0 else -1
    sy = 1 if dy >= 0 else -1
    diagonally_first = (a[0] + sx * delta, a[1] + sy * delta)
    diagonally_last = (end[0] - sx * delta, end[1] - sy * delta)
    return (
        (a, end),
        (a, (end[0], a[1]), end),
        (a, (a[0], end[1]), end),
        (a, diagonally_first, end),
        (a, diagonally_last, end),
    )


def _safe_terminal(
    start: Point,
    end: Point,
    obstacles: tuple[Obstacle, ...],
    envelope_mm: float,
) -> tuple[Point, ...] | None:
    routes: list[tuple[float, tuple[Point, ...]]] = []
    for points in _terminal_candidates(start, end):
        path = _simplify(points)
        if not is_hv45_path(path):
            continue
        if all(
            _segment_clear(a, b, obstacles, envelope_mm)
            for a, b in zip(path, path[1:], strict=False)
        ):
            cost = sum(
                hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(path, path[1:], strict=False)
            )
            routes.append((cost, path))
    return min(routes, key=lambda item: (item[0], len(item[1]), item[1]))[1] if routes else None


def _validate_input(
    start: Point,
    end: Point,
    obstacles: tuple[Obstacle, ...],
    width: float,
    clearance: float,
    step: float,
    margin: float,
    max_nodes: int,
) -> None:
    for number in (*start, *end, width, clearance, step, margin):
        if not isfinite(number):
            raise RoutePlanningError("Non-finite routing geometry is not supported")
    if width <= 0 or clearance < 0 or step <= 0 or margin <= 0:
        raise RoutePlanningError("Invalid track width, clearance, step or search margin")
    if start == end:
        raise RoutePlanningError("Pad endpoints overlap")
    if not 1 <= max_nodes <= 50000:
        raise RoutePlanningError("Invalid node budget")
    if len(obstacles) > 2000:
        raise RoutePlanningError("Obstacle count exceeds supported planning budget")
    for obstacle in obstacles:
        values = (
            (obstacle.x_mm, obstacle.y_mm, obstacle.radius_mm)
            if isinstance(obstacle, CircleObstacle)
            else (
                obstacle.x1_mm,
                obstacle.y1_mm,
                obstacle.x2_mm,
                obstacle.y2_mm,
                obstacle.radius_mm,
            )
        )
        if not all(isfinite(v) for v in values) or obstacle.radius_mm < 0:
            raise RoutePlanningError("Invalid obstacle envelope")


def plan_hv45_path(
    start: Point,
    end: Point,
    obstacles: tuple[Obstacle, ...],
    *,
    track_width_mm: float = 0.25,
    clearance_mm: float = 0.20,
    grid_mm: float = 0.25,
    margin_mm: float = 3.0,
    max_nodes: int = 20000,
) -> tuple[Point, ...]:
    """Plan a same-layer H/V/45 centerline, or fail closed.

    Obstacles must already be filtered to the intended copper layer and must
    conservatively include other-net pads, tracks, vias and keepouts.
    Missing/unknown board geometry is a caller error; this does not read KiCad.
    The planner never mutates a board and does not certify a DRC-clean result.
    """
    _validate_input(
        start, end, obstacles, track_width_mm, clearance_mm, grid_mm, margin_mm, max_nodes
    )
    envelope = track_width_mm / 2 + clearance_mm
    if not _segment_clear(start, start, obstacles, envelope):
        raise RoutePlanningError("Start pad is inside an obstacle")
    if not _segment_clear(end, end, obstacles, envelope):
        raise RoutePlanningError("End pad is inside an obstacle")

    direct = _safe_terminal(start, end, obstacles, envelope)
    if direct is not None:
        return direct

    if max(abs(end[0] - start[0]), abs(end[1] - start[1])) > 80:
        raise RoutePlanningError("Route exceeds bounded search extent")

    min_x = min(start[0], end[0]) - margin_mm
    max_x = max(start[0], end[0]) + margin_mm
    min_y = min(start[1], end[1]) - margin_mm
    max_y = max(start[1], end[1]) + margin_mm
    imin = floor((min_x - start[0]) / grid_mm)
    imax = ceil((max_x - start[0]) / grid_mm)
    jmin = floor((min_y - start[1]) / grid_mm)
    jmax = ceil((max_y - start[1]) / grid_mm)

    directions = ((1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1), (0, -1), (1, -1))

    def point(key: tuple[int, int]) -> Point:
        return (round(start[0] + key[0] * grid_mm, 8), round(start[1] + key[1] * grid_mm, 8))

    scores: dict[tuple[int, int], float] = {(0, 0): 0.0}
    parents: dict[tuple[int, int], tuple[int, int]] = {}
    heap: list[tuple[float, float, int, int]] = [
        (hypot(end[0] - start[0], end[1] - start[1]), 0.0, 0, 0)
    ]
    expanded = 0
    while heap:
        _estimate, cost, i, j = heappop(heap)
        key = (i, j)
        if cost > scores.get(key, float("inf")) + _EPS:
            continue
        expanded += 1
        if expanded > max_nodes:
            raise RoutePlanningError("Routing search budget exceeded")
        pos = point(key)
        if key != (0, 0):
            terminal = _safe_terminal(pos, end, obstacles, envelope)
            if terminal is not None:
                backwards: list[Point] = [pos]
                cursor = key
                while cursor in parents:
                    cursor = parents[cursor]
                    backwards.append(point(cursor))
                path = _simplify(tuple(reversed(backwards)) + terminal[1:])
                if is_hv45_path(path) and all(
                    _segment_clear(a, b, obstacles, envelope)
                    for a, b in zip(path, path[1:], strict=False)
                ):
                    return path

        for di, dj in directions:
            nxt = (i + di, j + dj)
            if not (imin <= nxt[0] <= imax and jmin <= nxt[1] <= jmax):
                continue
            future = point(nxt)
            if not _segment_clear(pos, future, obstacles, envelope):
                continue
            new_cost = cost + (sqrt(2) if di and dj else 1) * grid_mm
            if new_cost + _EPS >= scores.get(nxt, float("inf")):
                continue
            scores[nxt] = new_cost
            parents[nxt] = key
            heuristic = hypot(end[0] - future[0], end[1] - future[1])
            heappush(heap, (new_cost + heuristic, new_cost, nxt[0], nxt[1]))
    raise RoutePlanningError("No obstacle-free H/V/45 route within bounded search")

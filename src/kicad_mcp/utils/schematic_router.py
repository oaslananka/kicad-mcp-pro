"""Grid-based A* router for KiCad schematic wire segments."""

from __future__ import annotations

import heapq
from collections.abc import Callable, Iterable
from dataclasses import dataclass

Point = tuple[float, float]
Segment = tuple[float, float, float, float]

#: Coordinate tolerance in millimetres for coincidence tests.
_EPS = 1e-6

#: Price of one crossing, in grid steps.  A move costs 1.0 and a bend costs 3.0,
#: so 20 puts a crossing at roughly 20 grid steps (25.4 mm on the 1.27 mm
#: schematic grid): worth routing around, not worth an absurd detour.
#: Crossings stay *legal* -- a router that refuses them cannot connect a
#: non-planar sheet at all -- they are merely expensive.
CROSSING_PENALTY = 20.0


def point_on_segment(point: Point, segment: Segment, *, tolerance: float = _EPS) -> bool:
    """True when an orthogonal run passes through ``point``, ends included."""
    px, py = point
    x1, y1, x2, y2 = segment
    if abs(y1 - y2) <= tolerance:
        return (
            abs(py - y1) <= tolerance and min(x1, x2) - tolerance <= px <= max(x1, x2) + tolerance
        )
    if abs(x1 - x2) <= tolerance:
        return (
            abs(px - x1) <= tolerance and min(y1, y2) - tolerance <= py <= max(y1, y2) + tolerance
        )
    return False


def _at_endpoint(point: Point, segment: Segment, *, tolerance: float = _EPS) -> bool:
    """True when ``point`` coincides with either end of ``segment``."""
    px, py = point
    return (abs(px - segment[0]) <= tolerance and abs(py - segment[1]) <= tolerance) or (
        abs(px - segment[2]) <= tolerance and abs(py - segment[3]) <= tolerance
    )


def _inside_segment(point: Point, segment: Segment, *, tolerance: float = _EPS) -> bool:
    """True when ``point`` lies strictly inside an orthogonal run.

    Endpoints are excluded on purpose: standing on a foreign wire's end is
    already refused outright, so a node this accepts is one the path goes
    *through*, which is exactly one crossing.
    """
    return point_on_segment(point, segment, tolerance=tolerance) and not _at_endpoint(
        point, segment, tolerance=tolerance
    )


def _collinear_overlap(one: Segment, other: Segment, *, tolerance: float = _EPS) -> bool:
    """True when two aligned runs share length, touching ends included.

    KiCad unions wires that overlap or meet end-to-end, so both count as a
    merge.  A bare perpendicular crossing shares a single point and stays two
    nets, which is why the runner-up case returns ``False``.
    """
    if abs(one[1] - one[3]) <= tolerance and abs(other[1] - other[3]) <= tolerance:
        if abs(one[1] - other[1]) > tolerance:
            return False
        return (
            max(min(one[0], one[2]), min(other[0], other[2]))
            <= min(max(one[0], one[2]), max(other[0], other[2])) + tolerance
        )
    if abs(one[0] - one[2]) <= tolerance and abs(other[0] - other[2]) <= tolerance:
        if abs(one[0] - other[0]) > tolerance:
            return False
        return (
            max(min(one[1], one[3]), min(other[1], other[3]))
            <= min(max(one[1], one[3]), max(other[1], other[3])) + tolerance
        )
    return False


def segments_merge(one: Segment, other: Segment, *, tolerance: float = _EPS) -> bool:
    """True when KiCad's union-by-geometry rules would join two wire runs.

    Wires union when they overlap along a shared axis or when either one's
    endpoint lands anywhere on the other.  A bare perpendicular crossing does
    neither, which is why a router may pass over another net.
    """
    if _collinear_overlap(one, other, tolerance=tolerance):
        return True
    for point in ((one[0], one[1]), (one[2], one[3])):
        if point_on_segment(point, other, tolerance=tolerance):
            return True
    for point in ((other[0], other[1]), (other[2], other[3])):
        if point_on_segment(point, one, tolerance=tolerance):
            return True
    return False


def perpendicular_crossing(one: Segment, other: Segment, *, tolerance: float = _EPS) -> bool:
    """True when two orthogonal runs cross at a point interior to both.

    This is the measurement counterpart to the router's occupancy rules: it
    reports the crossings KiCad leaves unconnected, on the finished segments
    (escape stubs included), where the search only needed to price them.  A
    merge is never also a crossing, hence the guard.
    """
    if segments_merge(one, other, tolerance=tolerance):
        return False
    x1, y1, x2, y2 = one
    u1, v1, u2, v2 = other
    if abs(y1 - y2) <= tolerance and abs(u1 - u2) <= tolerance:
        return (
            min(x1, x2) + tolerance < u1 < max(x1, x2) - tolerance
            and min(v1, v2) + tolerance < y1 < max(v1, v2) - tolerance
        )
    if abs(x1 - x2) <= tolerance and abs(v1 - v2) <= tolerance:
        return (
            min(y1, y2) + tolerance < v1 < max(y1, y2) - tolerance
            and min(u1, u2) + tolerance < x1 < max(u1, u2) - tolerance
        )
    return False


def module_boundary_edges(
    rectangles: Iterable[tuple[float, float, float, float]],
) -> list[tuple[bool, float, float, float]]:
    """Each drawn rectangle as ``(is_vertical, fixed_coord, lo, hi)`` edges.

    A module boundary is only ever met one edge at a time, so the sides are
    flattened once here rather than rebuilt on every move of the search.
    """
    edges: list[tuple[bool, float, float, float]] = []
    for x_min, y_min, x_max, y_max in rectangles:
        edges.extend(
            (
                (True, x_min, y_min, y_max),
                (True, x_max, y_min, y_max),
                (False, y_min, x_min, x_max),
                (False, y_max, x_min, x_max),
            )
        )
    return edges


def hugs_boundary(
    segment: Segment,
    boundary_edges: Iterable[tuple[bool, float, float, float]],
    clearance_mm: float,
) -> bool:
    """True when a run travels alongside a drawn boundary closer than clearance.

    Only a *parallel* run can crowd a boundary.  Leaving a pin that sits on the
    boundary, or crossing the boundary to reach a pin inside it, is
    perpendicular and is exactly what the boundary is there to be crossed by,
    so those moves are never refused.  A run that merely passes the corner of a
    rectangle does not share its span and is likewise free.
    """
    x1, y1, x2, y2 = segment
    if abs(x1 - x2) <= _EPS and abs(y1 - y2) <= _EPS:
        return False
    vertical = abs(x1 - x2) <= _EPS
    if vertical:
        fixed, lo, hi = x1, min(y1, y2), max(y1, y2)
    else:
        fixed, lo, hi = y1, min(x1, x2), max(x1, x2)
    for edge_vertical, coord, edge_lo, edge_hi in boundary_edges:
        if edge_vertical != vertical:
            continue
        if abs(fixed - coord) >= clearance_mm - _EPS:
            continue
        if min(hi, edge_hi) - max(lo, edge_lo) <= _EPS:
            continue
        return True
    return False


@dataclass(frozen=True)
class PinOrientation:
    """Directions a route must leave and arrive in, when the caller knows them.

    Both come from the pins' outward normals, and they belong together: a route
    that leaves a pin along its normal and arrives against the far pin's normal
    is the shape a reader expects, and each is meaningless without the other.
    Passing them as one value also keeps ``route``'s signature readable.
    """

    start: tuple[int, int] | None = None
    goal: tuple[int, int] | None = None


@dataclass(frozen=True)
class RouterBBox:
    """Axis-aligned obstacle bounds in millimetres."""

    x_min: float
    y_min: float
    x_max: float
    y_max: float

    def contains(self, point: Point) -> bool:
        x_mm, y_mm = point
        return self.x_min <= x_mm <= self.x_max and self.y_min <= y_mm <= self.y_max


class SchematicRouter:
    """A* schematic router with Manhattan movement and bend penalties."""

    #: Spacing, in grid steps, that wires running alongside each other use in a
    #: hand-drawn sheet.  Measured on the reference board: of the wires with a
    #: parallel neighbour, 41 sit at 2 steps and none at 1, and 89% of all wire
    #: length runs alongside something.  A reader follows a bundle; a wire one
    #: step from its neighbour cannot be followed at all.
    BUNDLE_PITCH = 2
    #: A step running at BUNDLE_PITCH costs this fraction of a free step, so the
    #: search will pay extra length to join a bundle rather than stand alone.
    BUNDLE_DISCOUNT = 0.55
    #: Expansions allowed before a route is reported unroutable.  A full A3 sheet
    #: with routing channels needs more than the original budget.
    MAX_STEPS = 20000
    #: Closest a run may travel alongside a *drawn* boundary -- a hierarchical
    #: sheet's rectangle, or a bare rectangle a designer drew to fence off a
    #: self-contained block.  Measured on the reference sheet: no wire anywhere
    #: on it runs parallel to such an edge nearer than 2 steps, and none sits on
    #: one.  A wire hugging the edge reads as part of the drawing -- it stops
    #: looking like a connection and starts looking like the block's own border.
    BOUNDARY_CLEARANCE = 2

    def __init__(
        self,
        grid_mm: float = 2.54,
        obstacles: list[RouterBBox] | None = None,
        occupied: list[Segment] | None = None,
        crossing_penalty: float = CROSSING_PENALTY,
        boundaries: list[RouterBBox] | None = None,
    ) -> None:
        self.grid_mm = grid_mm
        self.obstacles = list(obstacles or [])
        #: Drawn rectangles that are not solid -- a route may still cross one to
        #: reach a pin inside it -- but that a run must not travel alongside.
        self.boundaries = list(boundaries or [])
        self.boundary_clearance_steps = self.BOUNDARY_CLEARANCE
        self._boundary_edges = module_boundary_edges(
            (box.x_min, box.y_min, box.x_max, box.y_max) for box in self.boundaries
        )
        #: Hard ceiling on expansions, so an unroutable pair reports rather than
        #: searching forever.  A class attribute rather than an argument: it is a
        #: safety budget, not a decision a caller makes per route.
        self.max_expansions = self.MAX_STEPS
        #: Wire geometry owned by *other* nets.  Unlike ``obstacles`` these are
        #: not solid: a route may cross one perpendicularly, because KiCad only
        #: unions a crossing when an endpoint lands on the other wire.  What it
        #: may not do is run along one, or turn on one.
        self.occupied = list(occupied or [])
        self.crossing_penalty = crossing_penalty
        #: Taken from the class constants rather than the signature: these are
        #: measured policy, not per-call decisions, and a caller that really needs
        #: a different value can set the attribute or subclass.
        self.bundle_step_discount = self.BUNDLE_DISCOUNT
        self.min_parallel_offset = self.BUNDLE_PITCH
        #: Search-scoped state, reset by ``route``.  Kept on the instance so the
        #: per-move rules can live in their own method without threading six
        #: arguments through every call.
        self._start_node: tuple[int, int] = (0, 0)
        self._end_node: tuple[int, int] = (0, 0)
        self._exempt: set[tuple[int, int]] = set()
        self._max_bends = 0
        self._goal_dir: tuple[int, int] | None = None
        self._kind_cache: dict[tuple[int, int], int] = {}
        self._crossing_cache: dict[tuple[int, int], int] = {}
        self._parallel_cache: dict[tuple[tuple[int, int], tuple[int, int]], int] = {}
        #: Span index by fixed coordinate, so a parallelism probe is a lookup
        #: rather than a scan over every foreign wire on every move.
        self._h_spans: dict[float, list[tuple[float, float]]] = {}
        self._v_spans: dict[float, list[tuple[float, float]]] = {}
        for ox1, oy1, ox2, oy2 in self.occupied:
            if abs(oy1 - oy2) <= _EPS and abs(ox1 - ox2) > _EPS:
                self._h_spans.setdefault(round(oy1, 4), []).append((min(ox1, ox2), max(ox1, ox2)))
            elif abs(ox1 - ox2) <= _EPS and abs(oy1 - oy2) > _EPS:
                self._v_spans.setdefault(round(ox1, 4), []).append((min(oy1, oy2), max(oy1, oy2)))

    def _grid(self, point: Point) -> tuple[int, int]:
        return (round(point[0] / self.grid_mm), round(point[1] / self.grid_mm))

    def _point(self, node: tuple[int, int]) -> Point:
        return (node[0] * self.grid_mm, node[1] * self.grid_mm)

    def _blocked(self, node: tuple[int, int], start: tuple[int, int], end: tuple[int, int]) -> bool:
        if node in {start, end}:
            return False
        point = self._point(node)
        return any(obstacle.contains(point) for obstacle in self.obstacles)

    def _hugs_boundary(self, current: tuple[int, int], nxt: tuple[int, int]) -> bool:
        """True when this move would run alongside a drawn boundary too closely."""
        return hugs_boundary(
            (
                self._point(current)[0],
                self._point(current)[1],
                self._point(nxt)[0],
                self._point(nxt)[1],
            ),
            self._boundary_edges,
            self.boundary_clearance_steps * self.grid_mm,
        )

    def _occupied_kind(self, node: tuple[int, int]) -> int:
        """How foreign wire geometry covers a grid node.

        ``0`` free, ``1`` inside a foreign run (a through-move is fine, a turn
        there would drop a T-junction), ``2`` on a foreign run's endpoint (not
        standable at all -- a wire ending on ours unions the two nets even when
        we pass straight through).
        """
        if not self.occupied:
            return 0
        cached = self._kind_cache.get(node)
        if cached is not None:
            return cached
        point = self._point(node)
        kind = 0
        for segment in self.occupied:
            if not point_on_segment(point, segment):
                continue
            if _at_endpoint(point, segment):
                kind = 2
                break
            kind = 1
        self._kind_cache[node] = kind
        return kind

    def _edge_overlaps_occupied(self, current: tuple[int, int], nxt: tuple[int, int]) -> bool:
        """True when a one-step move would run along a foreign wire."""
        if not self.occupied:
            return False
        here = self._point(current)
        there = self._point(nxt)
        edge = (here[0], here[1], there[0], there[1])
        return any(_collinear_overlap(edge, segment) for segment in self.occupied)

    def _crossings_at(self, node: tuple[int, int]) -> int:
        """How many foreign runs this node sits inside.

        A count rather than a flag, because two nets may cross the same point.
        Only reached for straight through-moves, so every run counted here is
        genuinely crossed rather than run along.
        """
        if not self.occupied:
            return 0
        cached = self._crossing_cache.get(node)
        if cached is None:
            point = self._point(node)
            cached = sum(1 for segment in self.occupied if _inside_segment(point, segment))
            self._crossing_cache[node] = cached
        return cached

    def _parallel_offset(self, node: tuple[int, int], direction: tuple[int, int]) -> int:
        """Grid steps to the nearest foreign wire running alongside this move.

        ``0`` when nothing runs parallel, otherwise the smallest offset found --
        capped at ``BUNDLE_PITCH`` because that is the only offset the caller
        rewards, and anything further away is not a bundle.  Only wires parallel
        to the move count: a perpendicular wire is a crossing, not a neighbour.
        """
        if not self.occupied:
            return 0
        key = (node, direction)
        cached = self._parallel_cache.get(key)
        if cached is not None:
            return cached
        x_mm, y_mm = self._point(node)
        result = 0
        for step in range(1, self.BUNDLE_PITCH + 1):
            for sign in (-1, 1):
                if direction[0] != 0:
                    probe = round(y_mm + sign * step * self.grid_mm, 4)
                    hit = any(
                        lo - _EPS <= x_mm <= hi + _EPS for lo, hi in self._h_spans.get(probe, ())
                    )
                else:
                    probe = round(x_mm + sign * step * self.grid_mm, 4)
                    hit = any(
                        lo - _EPS <= y_mm <= hi + _EPS for lo, hi in self._v_spans.get(probe, ())
                    )
                if hit:
                    result = step
                    break
            if result:
                break
        self._parallel_cache[key] = result
        return result

    def _heuristic(self, node: tuple[int, int], end: tuple[int, int]) -> float:
        """Admissible Manhattan lower bound for the active routing cost model."""
        distance = abs(node[0] - end[0]) + abs(node[1] - end[1])
        minimum_step_cost = min(1.0, self.bundle_step_discount) if self.occupied else 1.0
        return distance * minimum_step_cost

    @staticmethod
    def _emit_pop(
        callback: Callable[[tuple[int, int], float], None] | None,
        node: tuple[int, int],
        cost: float,
    ) -> None:
        if callback is not None:
            callback(node, cost)

    def route(
        self,
        start: Point,
        end: Point,
        max_bends: int = 4,
        orientation: PinOrientation | None = None,
        on_pop: Callable[[tuple[int, int], float], None] | None = None,
    ) -> list[Segment] | None:
        """Return routed Manhattan segments, or None if no bounded route is found.

        With ``occupied`` set the search also refuses to merge with another
        net: it will not run along a foreign wire (collinear overlap) and will
        not place a vertex or an endpoint on one.  Perpendicular crossings stay
        legal, matching KiCad's union-by-geometry rules, but each one is charged
        ``crossing_penalty`` so the search prefers a longer crossing-free route
        when one is cheap enough.  ``crossing_penalty=0`` restores the old
        shortest-path behaviour.

        ``start_dir`` is the direction the wire is already travelling when it
        reaches ``start`` -- normally the pin's own outward normal.  Without it
        the first move is free in every direction, so the route may turn at the
        pin for nothing; that unpriced turn makes two same-length candidates
        tie, and the tie is then settled arbitrarily.  ``goal_dir`` is the
        direction the wire must leave ``end`` in, so the hinge into the final
        stub is charged as well.

        ``on_pop`` receives ``(node, settled_cost)`` for each node the search
        settles, in order.  It exists so a visualisation can show *this* search
        rather than a copy of it -- a duplicated implementation drifts the moment
        a rule like the bundle discount is added, and then the animation draws a
        route the router never produced.
        """
        self._start_node = self._grid(start)
        self._end_node = self._grid(end)
        # The two endpoints are pins of the net being routed.  Foreign geometry
        # sitting on them is a pre-existing condition, not this route's doing.
        self._exempt = {self._start_node, self._end_node}
        self._max_bends = max_bends
        self._goal_dir = orientation.goal if orientation is not None else None
        self._kind_cache = {}
        self._crossing_cache = {}

        queue: list[tuple[float, int, tuple[int, int], tuple[int, int] | None, int]] = []
        start_dir = orientation.start if orientation is not None else None
        heapq.heappush(queue, (0.0, 0, self._start_node, start_dir, 0))
        came_from: dict[tuple[int, int], tuple[int, int] | None] = {self._start_node: None}
        best_cost: dict[tuple[int, int], float] = {self._start_node: 0.0}
        directions = [(1, 0), (-1, 0), (0, 1), (0, -1)]
        explored = 0

        while queue and explored < self.max_expansions:
            _, bends, current, previous_dir, _tie = heapq.heappop(queue)
            explored += 1
            self._emit_pop(on_pop, current, best_cost[current])
            if current == self._end_node:
                return self._segments_from_path(self._reconstruct(came_from, current))

            for direction in directions:
                nxt = (current[0] + direction[0], current[1] + direction[1])
                step = self._step_cost(current, nxt, direction, previous_dir, bends)
                if step is None:
                    continue
                move_cost, next_bends = step
                new_cost = best_cost[current] + move_cost
                if new_cost >= best_cost.get(nxt, float("inf")):
                    continue
                came_from[nxt] = current
                best_cost[nxt] = new_cost
                priority = new_cost + self._heuristic(nxt, self._end_node)
                heapq.heappush(queue, (priority, next_bends, nxt, direction, explored))
        return None

    def _bundle_multiplier(self, nxt: tuple[int, int], direction: tuple[int, int]) -> float | None:
        """Cost multiplier for a step, or ``None`` when it crowds a neighbour.

        Running alongside existing wire is the sheet's own idiom -- a bundle is
        what a reader follows -- so a step at the canonical pitch is discounted
        and a step closer than that is refused outright.  The pitch is measured,
        not chosen: of the wires on the reference sheet that have a parallel
        neighbour, 41 sit at two grid steps and none at one.
        """
        if not self.occupied:
            return 1.0
        offset = self._parallel_offset(nxt, direction)
        if offset and offset < self.min_parallel_offset:
            return None
        return self.bundle_step_discount if offset == self.BUNDLE_PITCH else 1.0

    def _is_step_refused(
        self,
        current: tuple[int, int],
        nxt: tuple[int, int],
        turning: bool,
    ) -> bool:
        if self._blocked(nxt, self._start_node, self._end_node):
            return True
        if turning and current not in self._exempt and self._occupied_kind(current) == 1:
            return True
        if nxt not in self._exempt and self._occupied_kind(nxt) == 2:
            return True
        if self._edge_overlaps_occupied(current, nxt):
            return True
        return self._hugs_boundary(current, nxt)

    def _arrival_penalty(self, nxt: tuple[int, int], direction: tuple[int, int]) -> float:
        if nxt == self._end_node and self._goal_dir is not None and direction != self._goal_dir:
            return 3.0
        return 0.0

    def _step_cost(
        self,
        current: tuple[int, int],
        nxt: tuple[int, int],
        direction: tuple[int, int],
        previous_dir: tuple[int, int] | None,
        bends: int,
    ) -> tuple[float, int] | None:
        """Cost of one move, or ``None`` when the move is refused.

        Lifted out of the search loop so the loop reads as a search: all the rules
        about *other* nets are here, and they are asymmetric on purpose.  Running
        along a foreign wire, turning on one, and landing an endpoint on one each
        make KiCad union two nets into a silent short, so they are refused; a
        perpendicular crossing is legal and merely priced.
        """
        turning = previous_dir is not None and previous_dir != direction
        if self._is_step_refused(current, nxt, turning):
            return None
        next_bends = bends + (1 if turning else 0)
        if next_bends > self._max_bends:
            return None
        multiplier = self._bundle_multiplier(nxt, direction)
        if multiplier is None:
            return None
        move_cost = 1.0 + (3.0 if turning else 0.0)
        if not turning:
            move_cost *= multiplier
        move_cost += self.crossing_penalty * self._crossings_at(nxt)
        move_cost += self._arrival_penalty(nxt, direction)
        return move_cost, next_bends

    @staticmethod
    def _reconstruct(
        came_from: dict[tuple[int, int], tuple[int, int] | None],
        current: tuple[int, int],
    ) -> list[tuple[int, int]]:
        path = [current]
        previous = came_from[current]
        while previous is not None:
            current = previous
            path.append(current)
            previous = came_from[current]
        path.reverse()
        return path

    def _segments_from_path(self, path: list[tuple[int, int]]) -> list[Segment]:
        if len(path) < 2:
            return []
        points = [self._point(node) for node in path]
        segments: list[Segment] = []
        start = points[0]
        previous = points[0]
        direction = (
            int(points[1][0] - points[0][0]),
            int(points[1][1] - points[0][1]),
        )
        for point in points[1:]:
            next_direction = (
                int(point[0] - previous[0]),
                int(point[1] - previous[1]),
            )
            if next_direction != direction:
                segments.append((start[0], start[1], previous[0], previous[1]))
                start = previous
                direction = next_direction
            previous = point
        segments.append((start[0], start[1], previous[0], previous[1]))
        return [segment for segment in segments if segment[:2] != segment[2:]]

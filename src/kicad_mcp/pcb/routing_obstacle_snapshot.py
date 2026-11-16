"""Conservative KiCad IPC copper envelopes for the bounded route planner.

This read-only adapter models supported board outlines and keepout polygons.
Unknown or incomplete native geometry remains a hard refusal; it is never
silently converted into an empty obstacle set.
"""

from __future__ import annotations

from collections.abc import Iterable
from math import acos, atan2, ceil, cos, hypot, isfinite, pi, sin
from typing import Protocol, cast

from kipy.board_types import (
    BoardArc,
    BoardCircle,
    BoardPolygon,
    BoardRectangle,
    BoardSegment,
    BoardShape,
    PadStackLayer,
)
from kipy.geometry import PolygonWithHoles
from kipy.proto.board.board_types_pb2 import BoardLayer, PadStackShape, ZoneType

from ..routing.path_planner import (
    BoardBoundary,
    CircleObstacle,
    Obstacle,
    PolygonObstacle,
    RoutePlanningError,
    SegmentObstacle,
    _segment_clear,
)
from ..utils.layers import resolve_layer
from ..utils.units import nm_to_mm
from .board_access import (
    board_pads,
    board_shapes,
    board_tracks,
    board_vias,
    board_zones,
)
from .geometry import point_xy_mm


class _PadLocation(Protocol):
    position: object


class _TrackGeometry(Protocol):
    layer: int
    start: object
    end: object
    width: int


class _ViaGeometry(Protocol):
    position: object
    diameter: int


_POINT_TOLERANCE_MM = 0.001
_ARC_SAGITTA_MM = 0.01


def _points_close(a: tuple[float, float], b: tuple[float, float]) -> bool:
    return hypot(a[0] - b[0], a[1] - b[1]) <= _POINT_TOLERANCE_MM


def _ring_area(vertices: tuple[tuple[float, float], ...]) -> float:
    return 0.5 * sum(
        a[0] * b[1] - b[0] * a[1]
        for a, b in zip(vertices, (*vertices[1:], vertices[0]), strict=True)
    )


def _sample_arc(
    start_point: object,
    mid_point: object,
    end_point: object,
) -> tuple[tuple[float, float], ...]:
    start = point_xy_mm(start_point)
    middle = point_xy_mm(mid_point)
    end = point_xy_mm(end_point)
    ax, ay = start
    bx, by = middle
    cx, cy = end
    determinant = 2 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    if abs(determinant) <= 1e-9:
        raise RoutePlanningError("Board arc has degenerate three-point geometry")

    a_squared = ax * ax + ay * ay
    b_squared = bx * bx + by * by
    c_squared = cx * cx + cy * cy
    center_x = (a_squared * (by - cy) + b_squared * (cy - ay) + c_squared * (ay - by)) / determinant
    center_y = (a_squared * (cx - bx) + b_squared * (ax - cx) + c_squared * (bx - ax)) / determinant
    radius = hypot(ax - center_x, ay - center_y)
    if not isfinite(radius) or radius <= _ARC_SAGITTA_MM:
        raise RoutePlanningError("Board arc radius is invalid")

    start_angle = atan2(ay - center_y, ax - center_x)
    middle_angle = atan2(by - center_y, bx - center_x)
    end_angle = atan2(cy - center_y, cx - center_x)
    counter_clockwise_sweep = (end_angle - start_angle) % (2 * pi)
    middle_sweep = (middle_angle - start_angle) % (2 * pi)
    sweep = (
        counter_clockwise_sweep
        if middle_sweep <= counter_clockwise_sweep + 1e-8
        else counter_clockwise_sweep - 2 * pi
    )
    if abs(sweep) <= 1e-8:
        raise RoutePlanningError("Board arc sweep is invalid")

    max_step = 2 * acos(max(-1.0, min(1.0, 1 - _ARC_SAGITTA_MM / radius)))
    if not isfinite(max_step) or max_step <= 0:
        raise RoutePlanningError("Board arc cannot be conservatively tessellated")
    steps = max(2, ceil(abs(sweep) / max_step))
    points = [
        (
            center_x + radius * cos(start_angle + sweep * index / steps),
            center_y + radius * sin(start_angle + sweep * index / steps),
        )
        for index in range(steps + 1)
    ]
    points[0] = start
    points[-1] = end
    return tuple(points)


def _polyline_points(polyline: object) -> tuple[tuple[float, float], ...]:
    if not getattr(polyline, "closed", False):
        raise RoutePlanningError("Native polygon outline is not closed")
    nodes = getattr(polyline, "nodes", None)
    if not nodes:
        raise RoutePlanningError("Native polygon outline has no vertices")

    points: list[tuple[float, float]] = []
    for node in nodes:
        if getattr(node, "has_point", False):
            points.append(point_xy_mm(node.point))
        elif getattr(node, "has_arc", False):
            points.extend(_sample_arc(node.arc.start, node.arc.mid, node.arc.end))
        else:
            raise RoutePlanningError("Native polygon contains an unsupported outline node")

    if len(points) > 1 and _points_close(points[0], points[-1]):
        points.pop()
    if len(points) < 3:
        raise RoutePlanningError("Native polygon outline has fewer than three vertices")
    return tuple(points)


def _polygon_obstacle_from_outline(outline: PolygonWithHoles) -> PolygonObstacle:
    outer = _polyline_points(outline.outline)
    holes = tuple(_polyline_points(hole) for hole in getattr(outline, "holes", ()))
    return PolygonObstacle(vertices=outer, holes=holes)


def _edge_shape_points(shape: object) -> tuple[tuple[float, float], ...]:
    if isinstance(shape, BoardSegment):
        start = point_xy_mm(shape.start)
        end = point_xy_mm(shape.end)
        if _points_close(start, end):
            raise RoutePlanningError("Invalid board edge segment geometry: zero length")
        return (start, end)
    if isinstance(shape, BoardArc):
        return _sample_arc(shape.start, shape.mid, shape.end)
    raise RoutePlanningError("Board outline contains an unsupported native shape")


def _stitch_edge_loops(
    edge_shapes: list[object],
) -> tuple[tuple[tuple[float, float], ...], ...]:
    remaining = [_edge_shape_points(shape) for shape in edge_shapes]
    loops: list[tuple[tuple[float, float], ...]] = []

    while remaining:
        current = list(remaining.pop(0))
        while not _points_close(current[-1], current[0]):
            match_index: int | None = None
            next_points: list[tuple[float, float]] | None = None
            for index, candidate in enumerate(remaining):
                if _points_close(candidate[0], current[-1]):
                    match_index = index
                    next_points = list(candidate[1:])
                    break
                if _points_close(candidate[-1], current[-1]):
                    match_index = index
                    next_points = list(reversed(candidate))[1:]
                    break
            if match_index is None or next_points is None:
                raise RoutePlanningError("Board edge outline is open or disconnected")
            current.extend(next_points)
            remaining.pop(match_index)
            if len(current) > 20_000:
                raise RoutePlanningError("Board edge outline is unexpectedly complex")

        current[-1] = current[0]
        ring = tuple(current[:-1])
        if len(ring) < 3:
            raise RoutePlanningError("Board edge outline has fewer than three vertices")
        loops.append(ring)

    return tuple(loops)


def _rectangle_ring(shape: BoardRectangle) -> tuple[tuple[float, float], ...]:
    top_left = point_xy_mm(shape.top_left)
    bottom_right = point_xy_mm(shape.bottom_right)
    if bottom_right[0] <= top_left[0] or bottom_right[1] <= top_left[1]:
        raise RoutePlanningError("Invalid board edge rectangle")
    return (
        top_left,
        (bottom_right[0], top_left[1]),
        bottom_right,
        (top_left[0], bottom_right[1]),
    )


def _boundary_from_loops(
    loops: tuple[tuple[tuple[float, float], ...], ...],
) -> BoardBoundary:
    if not loops:
        raise RoutePlanningError("Board edge outline is empty")
    ordered = sorted(loops, key=lambda ring: abs(_ring_area(ring)), reverse=True)
    return BoardBoundary(vertices=ordered[0], holes=tuple(ordered[1:]))


def _board_boundary_from_shapes(shapes: Iterable[object]) -> BoardBoundary | None:
    edge_shapes = [
        shape for shape in shapes if getattr(shape, "layer", None) == BoardLayer.BL_Edge_Cuts
    ]
    if not edge_shapes:
        return None

    if len(edge_shapes) > 1 and all(isinstance(shape, BoardRectangle) for shape in edge_shapes):
        raise RoutePlanningError("Multiple board edge rectangles require geometry review")
    if all(isinstance(shape, BoardRectangle) for shape in edge_shapes):
        loops = tuple(_rectangle_ring(cast(BoardRectangle, shape)) for shape in edge_shapes)
        return _boundary_from_loops(loops)

    if all(isinstance(shape, (BoardSegment, BoardArc)) for shape in edge_shapes):
        return _boundary_from_loops(_stitch_edge_loops(edge_shapes))

    raise RoutePlanningError("Mixed or unsupported board edge shape geometry requires review")


def _custom_primitive_radius_mm(shape: BoardShape) -> float:
    """Enclose all copper around the pad origin, regardless of pad rotation."""
    radius: float
    if isinstance(shape, BoardCircle):
        center = point_xy_mm(shape.center)
        radius = hypot(*center) + nm_to_mm(shape.radius())
    elif isinstance(shape, BoardSegment):
        radius = max(hypot(*point_xy_mm(point)) for point in (shape.start, shape.end))
    elif isinstance(shape, BoardArc):
        radius = max(hypot(*point) for point in _sample_arc(shape.start, shape.mid, shape.end))
        radius += _ARC_SAGITTA_MM
    elif isinstance(shape, BoardRectangle):
        top_left, bottom_right = point_xy_mm(shape.top_left), point_xy_mm(shape.bottom_right)
        radius = max(
            hypot(x, y)
            for x in (top_left[0], bottom_right[0])
            for y in (top_left[1], bottom_right[1])
        )
    elif isinstance(shape, BoardPolygon):
        polygons = shape.polygons
        if not polygons:
            raise RoutePlanningError("Custom pad polygon primitives are empty")
        radius = (
            max(
                hypot(*point)
                for polygon in polygons
                for ring in (polygon.outline, *polygon.holes)
                for point in _polyline_points(ring)
            )
            + _ARC_SAGITTA_MM
        )
    else:
        raise RoutePlanningError("Unsupported custom pad copper primitive")
    radius += _shape_width_radius_mm(shape)
    if not isfinite(radius) or radius <= 0:
        raise RoutePlanningError("Custom pad has invalid copper primitive geometry")
    return radius


def _custom_pad_radius_mm(copper_layer: PadStackLayer, width: float, height: float) -> float:
    primitives = copper_layer.custom_shapes
    if (
        not primitives
        or len(primitives) > 128
        or len(primitives) != len(copper_layer.proto.custom_shapes)
    ):
        raise RoutePlanningError("Incomplete custom pad copper primitives")
    return max(
        hypot(width, height) / 2,
        *(_custom_primitive_radius_mm(primitive) for primitive in primitives),
    )


def _pad_radius_mm(pad: object, layer_id: int) -> float:
    stack = getattr(pad, "padstack", None)
    if stack is None:
        raise RoutePlanningError("Pad stack geometry unavailable")
    copper_layer = stack.copper_layer(layer_id)
    if copper_layer is None and layer_id in stack.layers:
        # KiCad PTH PST_NORMAL stores one F_Cu geometry template shared across layers.
        copper_layer = stack.copper_layer(BoardLayer.BL_F_Cu)
    if copper_layer is None:
        raise RoutePlanningError("Copper pad shape is unavailable")
    shape = PadStackShape.Name(copper_layer.shape)
    if "TRAPEZOID" in shape:
        raise RoutePlanningError("Unsupported trapezoid copper pad shape")
    width = nm_to_mm(copper_layer.size.x)
    height = nm_to_mm(copper_layer.size.y)
    offset = point_xy_mm(copper_layer.offset)
    if width <= 0 or height <= 0:
        raise RoutePlanningError("Copper pad has no usable dimensions")
    # Custom primitive coordinates are pad-local; pad rotation cannot increase
    # the maximum radial distance. Offset is applied conservatively afterward.
    radius = (
        _custom_pad_radius_mm(copper_layer, width, height)
        if "CUSTOM" in shape
        else max(width, height) / 2
        if shape == "PSS_CIRCLE"
        else hypot(width, height) / 2
    )
    return radius + hypot(*offset)


def _via_radius_mm(via: object) -> float:
    try:
        diameter = nm_to_mm(cast(_ViaGeometry, via).diameter)
    except (AttributeError, ValueError, IndexError) as exc:
        raise RoutePlanningError("Unsupported via copper geometry") from exc
    if diameter <= 0:
        raise RoutePlanningError("Via copper diameter is invalid")
    return diameter / 2


def _shape_width_radius_mm(shape: BoardShape) -> float:
    try:
        width = nm_to_mm(shape.attributes.stroke.width)
    except (AttributeError, TypeError, ValueError) as exc:
        raise RoutePlanningError("Native copper shape stroke is unavailable") from exc
    if not isfinite(width) or width < 0:
        raise RoutePlanningError("Native copper shape has invalid stroke width")
    return width / 2


def _shape_obstacles(shapes: Iterable[object], layer_id: int) -> list[Obstacle]:
    obstacles: list[Obstacle] = []
    for shape in shapes:
        shape_layer = getattr(shape, "layer", None)
        if shape_layer == BoardLayer.BL_Edge_Cuts:
            continue
        if shape_layer is None:
            raise RoutePlanningError("Native board shape has unknown layer")
        if shape_layer != layer_id:
            continue

        if not isinstance(shape, (BoardSegment, BoardArc)):
            raise RoutePlanningError("Native copper shape unsupported for planning")
        radius = _shape_width_radius_mm(shape)
        if isinstance(shape, BoardSegment):
            start = point_xy_mm(shape.start)
            end = point_xy_mm(shape.end)
            if _points_close(start, end):
                raise RoutePlanningError("Native copper segment has zero length")
            obstacles.append(SegmentObstacle(*start, *end, radius))
        elif isinstance(shape, BoardArc):
            points = _sample_arc(shape.start, shape.mid, shape.end)
            obstacles.extend(
                SegmentObstacle(*start, *end, radius)
                for start, end in zip(points, points[1:], strict=True)
            )
        else:
            raise RoutePlanningError("Native copper shape unsupported for planning")
    return obstacles


def _zone_obstacles(
    zones: Iterable[object],
    layer_id: int,
    *,
    for_via: bool,
    routing_net: str | None = None,
) -> list[Obstacle]:
    obstacles: list[Obstacle] = []
    for zone in zones:
        layers = getattr(zone, "layers", None)
        if layers is None:
            raise RoutePlanningError("Copper zone layer membership unavailable")
        if layer_id not in layers:
            continue

        zone_type = getattr(zone, "type", None)
        if zone_type == ZoneType.ZT_RULE_AREA:
            settings = getattr(getattr(zone, "proto", None), "rule_area_settings", None)
            if settings is None:
                raise RoutePlanningError("Rule-area keepout settings unavailable")
            blocks_tracks = bool(settings.keepout_tracks)
            blocks_vias = bool(settings.keepout_vias)
            if blocks_tracks or (for_via and blocks_vias):
                outline = getattr(zone, "outline", None)
                if outline is None:
                    raise RoutePlanningError("Rule-area keepout outline unavailable")
                obstacles.append(_polygon_obstacle_from_outline(outline))
            continue

        if zone_type == ZoneType.ZT_COPPER:
            if (
                routing_net is not None
                and getattr(getattr(zone, "net", None), "name", None) == routing_net
            ):
                continue
            raise RoutePlanningError(
                "Copper zone fill on the routing layer is not yet safely modelled"
            )

        raise RoutePlanningError("Unknown zone type intersects the routing layer")
    return obstacles


def _validate_outline_endpoints(
    pads: Iterable[object],
    excluded_pad_ids: frozenset[str],
    boundary: BoardBoundary | None,
    *,
    require_outline: bool,
    expected_endpoint_count: int,
) -> None:
    if require_outline and boundary is None:
        raise RoutePlanningError(
            "No supported closed board outline; route planning requires a native boundary"
        )
    if boundary is None:
        return

    excluded_points = [
        point_xy_mm(cast(_PadLocation, pad).position)
        for pad in pads
        if getattr(getattr(pad, "id", None), "value", None) in excluded_pad_ids
    ]
    if (
        expected_endpoint_count not in (1, 2, 4)
        or len(excluded_points) != expected_endpoint_count
        or not all(_segment_clear(point, point, (boundary,), 0.0) for point in excluded_points)
    ):
        raise RoutePlanningError("Route endpoints are not safely inside board outline")


def _pad_obstacle(pad: object, layer_id: int) -> Obstacle:
    center = point_xy_mm(cast(_PadLocation, pad).position)
    stack = getattr(pad, "padstack", None)
    if stack is None:
        raise RoutePlanningError("Pad stack geometry unavailable")
    copper_layer = stack.copper_layer(layer_id)
    if copper_layer is None and layer_id in stack.layers:
        copper_layer = stack.copper_layer(BoardLayer.BL_F_Cu)
    if copper_layer is None:
        raise RoutePlanningError("Copper pad shape is unavailable")
    shape = PadStackShape.Name(copper_layer.shape)
    rectangular_shapes = {
        "PSS_RECT",
        "PSS_RECTANGLE",
        "PSS_ROUNDRECT",
        "PSS_OVAL",
        "PSS_CHAMFERED_RECT",
    }
    if shape in rectangular_shapes:
        width = nm_to_mm(copper_layer.size.x)
        height = nm_to_mm(copper_layer.size.y)
        offset = point_xy_mm(copper_layer.offset)
        angle = stack.angle.degrees * pi / 180
        if not all(isfinite(v) for v in (width, height, *offset, angle)) or (
            width <= 0 or height <= 0
        ):
            raise RoutePlanningError("Invalid rectangular copper pad geometry")
        # An axis-aligned box encloses the rotated full rectangle, including
        # every roundrect/oval/chamfered variant; the offset is bounded radially.
        dx = abs(cos(angle)) * width / 2 + abs(sin(angle)) * height / 2 + hypot(*offset)
        dy = abs(sin(angle)) * width / 2 + abs(cos(angle)) * height / 2 + hypot(*offset)
        return PolygonObstacle(
            (
                (center[0] - dx, center[1] - dy),
                (center[0] + dx, center[1] - dy),
                (center[0] + dx, center[1] + dy),
                (center[0] - dx, center[1] + dy),
            )
        )
    return CircleObstacle(center[0], center[1], _pad_radius_mm(pad, layer_id))


def _pad_obstacles(
    pads: Iterable[object],
    layer_id: int,
    excluded_pad_ids: frozenset[str],
    routing_net: str | None = None,
) -> list[Obstacle]:
    obstacles: list[Obstacle] = []
    for pad in pads:
        identity = getattr(getattr(pad, "id", None), "value", None)
        if not identity:
            raise RoutePlanningError("A pad has no stable native identity")
        if identity in excluded_pad_ids or (
            routing_net is not None
            and getattr(getattr(pad, "net", None), "name", None) == routing_net
        ):
            continue
        stack = getattr(pad, "padstack", None)
        if stack is None:
            raise RoutePlanningError("Pad stack unavailable")
        if not stack.layers:
            raise RoutePlanningError("Unknown pad layer membership")
        if layer_id not in stack.layers:
            continue
        obstacles.append(_pad_obstacle(pad, layer_id))
    return obstacles


def _track_obstacles(
    tracks: Iterable[object], layer_id: int, routing_net: str | None = None
) -> list[Obstacle]:
    obstacles: list[Obstacle] = []
    for item in tracks:
        track = cast(_TrackGeometry, item)
        if track.layer != layer_id:
            continue
        if (
            routing_net is not None
            and getattr(getattr(track, "net", None), "name", None) == routing_net
        ):
            continue
        start = point_xy_mm(track.start)
        end = point_xy_mm(track.end)
        radius = nm_to_mm(track.width) / 2
        if radius <= 0 or not isfinite(radius):
            raise RoutePlanningError("Existing track has invalid width")
        obstacles.append(SegmentObstacle(*start, *end, radius))
    return obstacles


def _via_obstacles(
    vias: Iterable[object], layer_id: int, routing_net: str | None = None
) -> list[Obstacle]:
    obstacles: list[Obstacle] = []
    for item in vias:
        via = cast(_ViaGeometry, item)
        stack = getattr(via, "padstack", None)
        if stack is None:
            raise RoutePlanningError("Via stack unavailable")
        if not stack.layers:
            raise RoutePlanningError("Unknown via layer membership")
        if layer_id not in stack.layers:
            continue
        if (
            routing_net is not None
            and getattr(getattr(via, "net", None), "name", None) == routing_net
        ):
            continue
        center = point_xy_mm(via.position)
        obstacles.append(CircleObstacle(center[0], center[1], _via_radius_mm(via)))
    return obstacles


def snapshot_route_obstacles(
    board: object,
    layer: str,
    excluded_pad_ids: frozenset[str],
    *,
    require_outline: bool = False,
    expected_endpoint_count: int = 2,
    for_via: bool = False,
    routing_net: str | None = None,
) -> tuple[Obstacle, ...]:
    """Read supported copper, keepout and board-boundary geometry, or refuse."""
    layer_id = resolve_layer(layer)
    if not layer.endswith("_Cu"):
        raise RoutePlanningError("Routing requires a copper layer")

    try:
        zones = board_zones(board)
        shapes = board_shapes(board)
        pads = board_pads(board)
        tracks = board_tracks(board)
        vias = board_vias(board)
    except Exception as exc:
        raise RoutePlanningError("Could not read complete native board obstacle geometry") from exc

    if routing_net is not None:
        selected = [
            pad
            for pad in pads
            if getattr(getattr(pad, "id", None), "value", None) in excluded_pad_ids
        ]
        if (
            not routing_net
            or len(selected) != expected_endpoint_count
            or any(
                getattr(getattr(pad, "net", None), "name", None) != routing_net for pad in selected
            )
        ):
            raise RoutePlanningError("Routing net does not match native endpoint pad nets")

    boundary = _board_boundary_from_shapes(shapes)
    _validate_outline_endpoints(
        pads,
        excluded_pad_ids,
        boundary,
        require_outline=require_outline,
        expected_endpoint_count=expected_endpoint_count,
    )

    obstacles: list[Obstacle] = []
    if boundary is not None:
        obstacles.append(boundary)
    obstacles.extend(_shape_obstacles(shapes, layer_id))
    obstacles.extend(_zone_obstacles(zones, layer_id, for_via=for_via, routing_net=routing_net))
    obstacles.extend(_pad_obstacles(pads, layer_id, excluded_pad_ids, routing_net=routing_net))
    obstacles.extend(_track_obstacles(tracks, layer_id, routing_net=routing_net))
    obstacles.extend(_via_obstacles(vias, layer_id, routing_net=routing_net))
    return tuple(obstacles)

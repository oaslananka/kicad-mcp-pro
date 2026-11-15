"""Conservative KiCad IPC copper envelopes for the bounded route planner.

This is a read-only adapter. Unsupported geometries are errors, never empty
obstacle lists; the caller must not automatically write these candidate routes.
"""

from __future__ import annotations

from math import hypot, isfinite
from typing import Protocol, cast

from kipy.board_types import BoardRectangle, BoardSegment
from kipy.proto.board.board_types_pb2 import BoardLayer, PadStackShape

from ..routing.path_planner import CircleObstacle, Obstacle, RoutePlanningError, SegmentObstacle
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
    if "CUSTOM" in shape or "TRAPEZOID" in shape:
        raise RoutePlanningError("Unsupported custom copper pad shape")
    width = nm_to_mm(copper_layer.size.x)
    height = nm_to_mm(copper_layer.size.y)
    offset = point_xy_mm(copper_layer.offset)
    if width <= 0 or height <= 0:
        raise RoutePlanningError("Copper pad has no usable dimensions")
    # A circle that fully encloses a rotated oval/rect/roundrect is conservative.
    return hypot(width, height) / 2 + hypot(*offset)


def _via_radius_mm(via: object) -> float:
    try:
        diameter = nm_to_mm(cast(_ViaGeometry, via).diameter)
    except (AttributeError, ValueError, IndexError) as exc:
        raise RoutePlanningError("Unsupported via copper geometry") from exc
    if diameter <= 0:
        raise RoutePlanningError("Via copper diameter is invalid")
    return diameter / 2


def _rectangle_from_edge_segments(
    segments: list[SegmentObstacle],
) -> tuple[float, float, float, float]:
    """Accept exactly four straight, closed axis-aligned board edge segments."""
    if len(segments) != 4:
        raise RoutePlanningError("Board edge outline must contain four closed segments")
    endpoints = [
        ((segment.x1_mm, segment.y1_mm), (segment.x2_mm, segment.y2_mm)) for segment in segments
    ]
    x_values = sorted({x for pair in endpoints for x, _ in pair})
    y_values = sorted({y for pair in endpoints for _, y in pair})
    if len(x_values) != 2 or len(y_values) != 2:
        raise RoutePlanningError("Board edge segments are not a rectangle")
    x1, x2 = x_values
    y1, y2 = y_values
    if x1 >= x2 or y1 >= y2:
        raise RoutePlanningError("Board edge outline has no positive area")
    corners = ((x1, y1), (x2, y1), (x2, y2), (x1, y2))
    expected = {frozenset((a, b)) for a, b in zip(corners, corners[1:] + corners[:1], strict=False)}
    observed = {frozenset(pair) for pair in endpoints}
    if observed != expected or len(observed) != 4:
        raise RoutePlanningError("Board edge outline is open, duplicated or skewed")
    return x1, y1, x2, y2


def snapshot_route_obstacles(
    board: object,
    layer: str,
    excluded_pad_ids: frozenset[str],
    *,
    require_outline: bool = False,
    expected_endpoint_count: int = 2,
) -> tuple[Obstacle, ...]:
    """Read all supported copper obstacles on one layer, or refuse incomplete state."""
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

    for zone in zones:
        layers = getattr(zone, "layers", None)
        if layers is None or layer_id in layers:
            raise RoutePlanningError("Copper zone geometry cannot be safely planned")
    obstacles: list[Obstacle] = []
    edge_rectangles: list[tuple[float, float, float, float]] = []
    edge_segments: list[SegmentObstacle] = []
    for shape in shapes:
        shape_layer = getattr(shape, "layer", None)
        if shape_layer == BoardLayer.BL_Edge_Cuts and isinstance(shape, BoardRectangle):
            a = point_xy_mm(shape.top_left)
            b = point_xy_mm(shape.bottom_right)
            if b[0] <= a[0] or b[1] <= a[1]:
                raise RoutePlanningError("Invalid board edge rectangle")
            width = nm_to_mm(shape.attributes.stroke.width)
            if width < 0:
                raise RoutePlanningError("Invalid board outline stroke")
            radius = width / 2
            obstacles.extend(
                (
                    SegmentObstacle(a[0], a[1], b[0], a[1], radius),
                    SegmentObstacle(b[0], a[1], b[0], b[1], radius),
                    SegmentObstacle(b[0], b[1], a[0], b[1], radius),
                    SegmentObstacle(a[0], b[1], a[0], a[1], radius),
                )
            )
            edge_rectangles.append((a[0], a[1], b[0], b[1]))
        elif shape_layer == BoardLayer.BL_Edge_Cuts and isinstance(shape, BoardSegment):
            a = point_xy_mm(shape.start)
            b = point_xy_mm(shape.end)
            width = nm_to_mm(shape.attributes.stroke.width)
            if a == b or not isfinite(width) or width < 0:
                raise RoutePlanningError("Invalid board edge segment geometry")
            edge_segments.append(SegmentObstacle(*a, *b, width / 2))
        elif shape_layer in (layer_id, BoardLayer.BL_Edge_Cuts) or shape_layer is None:
            raise RoutePlanningError("Native board edge/copper shape unsupported for planning")

    if edge_segments:
        if edge_rectangles:
            raise RoutePlanningError("Mixed board edge outline types require geometry review")
        edge_rectangles.append(_rectangle_from_edge_segments(edge_segments))
        obstacles.extend(edge_segments)
    if len(edge_rectangles) > 1:
        raise RoutePlanningError("Multiple board edge rectangles require geometry review")
    if require_outline and not edge_rectangles:
        raise RoutePlanningError(
            "No supported board outline; route planning requires a closed rectangle"
        )
    if edge_rectangles:
        x1, y1, x2, y2 = edge_rectangles[0]
        excluded_points = [
            point_xy_mm(cast(_PadLocation, pad).position)
            for pad in pads
            if getattr(getattr(pad, "id", None), "value", None) in excluded_pad_ids
        ]
        if (
            expected_endpoint_count not in (1, 2, 4)
            or len(excluded_points) != expected_endpoint_count
            or not all(x1 < x < x2 and y1 < y < y2 for x, y in excluded_points)
        ):
            raise RoutePlanningError("Route endpoints are not safely inside board outline")

    for pad in pads:
        identity = getattr(getattr(pad, "id", None), "value", None)
        if not identity:
            raise RoutePlanningError("A pad has no stable native identity")
        if identity in excluded_pad_ids:
            continue
        stack = getattr(pad, "padstack", None)
        if stack is None:
            raise RoutePlanningError("Pad stack unavailable")
        if not stack.layers:
            raise RoutePlanningError("Unknown pad layer membership")
        if layer_id not in stack.layers:
            continue
        center = point_xy_mm(cast(_PadLocation, pad).position)
        radius = _pad_radius_mm(pad, layer_id)
        obstacles.append(CircleObstacle(center[0], center[1], radius))

    for item in tracks:
        track = cast(_TrackGeometry, item)
        if track.layer != layer_id:
            continue
        start = point_xy_mm(track.start)
        end = point_xy_mm(track.end)
        radius = nm_to_mm(track.width) / 2
        if radius <= 0 or not isfinite(radius):
            raise RoutePlanningError("Existing track has invalid width")
        obstacles.append(SegmentObstacle(*start, *end, radius))

    for item in vias:
        via = cast(_ViaGeometry, item)
        stack = getattr(via, "padstack", None)
        if stack is None:
            raise RoutePlanningError("Via stack unavailable")
        if not stack.layers:
            raise RoutePlanningError("Unknown via layer membership")
        if layer_id not in stack.layers:
            continue
        center = point_xy_mm(via.position)
        obstacles.append(CircleObstacle(center[0], center[1], _via_radius_mm(via)))

    return tuple(obstacles)

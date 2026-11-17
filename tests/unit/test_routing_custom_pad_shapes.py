"""Custom native pads must contribute their full copper primitive envelopes."""

from __future__ import annotations

import pytest
from kipy.board_types import (
    BoardArc,
    BoardCircle,
    BoardPolygon,
    BoardRectangle,
    BoardSegment,
    BoardShape,
    Pad,
)
from kipy.geometry import PolygonWithHoles, PolyLine, PolyLineNode, Vector2
from kipy.proto.board.board_types_pb2 import BoardLayer, PadStackShape

from kicad_mcp.pcb.routing_obstacle_snapshot import (
    _custom_primitive_radius_mm,
    _pad_radius_mm,
    _polyline_points,
    _sample_arc,
)
from kicad_mcp.routing.path_planner import RoutePlanningError


def _custom_pad(*, with_primitives: bool = True) -> Pad:
    pad = Pad()
    pad.id.value = "custom-test-pad"
    pad.position = Vector2.from_xy_mm(10, 10)
    pad.padstack.layers = [BoardLayer.BL_F_Cu]
    layer = pad.padstack.copper_layers[0]
    layer.shape = PadStackShape.PSS_CUSTOM
    layer.size = Vector2.from_xy_mm(1, 0.5)
    if with_primitives:
        circle = BoardCircle()
        circle.center = Vector2.from_xy_mm(0, 0.25)
        circle.radius_point = Vector2.from_xy_mm(0.5, 0.25)
        polygon = BoardPolygon()
        region = PolygonWithHoles()
        for x, y in ((0.5, 0.75), (0, 0.75), (0, -0.75), (0.5, -0.75)):
            region.outline.append(PolyLineNode.from_point(Vector2.from_xy_mm(x, y)))
        region.outline.closed = True
        polygon.polygons.append(region)
        layer.custom_shapes = [circle, polygon]
    return pad


def test_custom_pad_obstacle_encloses_all_real_copper_primitives() -> None:
    pad = _custom_pad()
    radius = _pad_radius_mm(pad, BoardLayer.BL_F_Cu)
    assert radius >= (0.5**2 + 0.75**2) ** 0.5
    assert radius < 1.0


def test_custom_pad_without_readable_primitives_refuses_instead_of_guessing() -> None:
    pad = _custom_pad(with_primitives=False)
    with pytest.raises(RoutePlanningError, match="custom|primitive"):
        _pad_radius_mm(pad, BoardLayer.BL_F_Cu)


def test_degenerate_native_arc_is_refused_before_tessellation() -> None:
    points = [Vector2.from_xy_mm(x, 0.0) for x in (0, 1, 2)]
    with pytest.raises(RoutePlanningError, match="degenerate"):
        _sample_arc(*points)


def test_native_arc_smaller_than_the_precision_budget_is_refused() -> None:
    points = [
        Vector2.from_xy_mm(0.005, 0.0),
        Vector2.from_xy_mm(0.0, 0.005),
        Vector2.from_xy_mm(-0.005, 0.0),
    ]
    with pytest.raises(RoutePlanningError, match="radius"):
        _sample_arc(*points)


def test_custom_segment_arc_and_rectangle_keep_all_primitive_copper_in_bounds() -> None:
    segment = BoardSegment()
    segment.start = Vector2.from_xy_mm(0, 0)
    segment.end = Vector2.from_xy_mm(1, 0)

    arc = BoardArc()
    arc.start = Vector2.from_xy_mm(1, 0)
    arc.mid = Vector2.from_xy_mm(1, 1)
    arc.end = Vector2.from_xy_mm(0, 1)

    rectangle = BoardRectangle()
    rectangle.top_left = Vector2.from_xy_mm(0, 0)
    rectangle.bottom_right = Vector2.from_xy_mm(1, 1)

    assert _custom_primitive_radius_mm(segment) == pytest.approx(1.0)
    assert _custom_primitive_radius_mm(arc) >= 1.0
    assert _custom_primitive_radius_mm(rectangle) == pytest.approx(2**0.5)


def test_unclosed_and_empty_native_polygon_nodes_cannot_be_silently_skipped() -> None:
    polyline = PolyLine()
    with pytest.raises(RoutePlanningError, match="not closed"):
        _polyline_points(polyline)
    polyline.closed = True
    with pytest.raises(RoutePlanningError, match="no vertices"):
        _polyline_points(polyline)


def test_unreadable_custom_pad_primitives_fail_closed() -> None:
    with pytest.raises(RoutePlanningError, match="empty"):
        _custom_primitive_radius_mm(BoardPolygon())
    with pytest.raises(RoutePlanningError, match="Unsupported custom"):
        _custom_primitive_radius_mm(BoardShape())

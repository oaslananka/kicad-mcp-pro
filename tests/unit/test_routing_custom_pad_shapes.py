"""Custom native pads must contribute their full copper primitive envelopes."""

from __future__ import annotations

import pytest
from kipy.board_types import BoardCircle, BoardPolygon, Pad
from kipy.geometry import PolygonWithHoles, PolyLineNode, Vector2
from kipy.proto.board.board_types_pb2 import BoardLayer, PadStackShape

from kicad_mcp.pcb.routing_obstacle_snapshot import _pad_radius_mm
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
    with pytest.raises(RoutePlanningError, match="custom|primitive"):
        _pad_radius_mm(_custom_pad(with_primitives=False), BoardLayer.BL_F_Cu)

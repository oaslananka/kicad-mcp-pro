"""Native board obstacles must fail closed on unsupported copper geometry."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from kipy.board_types import BoardLayer, Pad, Track
from kipy.geometry import Vector2

from kicad_mcp.pcb.routing_obstacle_snapshot import snapshot_route_obstacles
from kicad_mcp.routing.path_planner import CircleObstacle, RoutePlanningError, SegmentObstacle


def _board(*, pads=(), tracks=(), vias=(), zones=(), shapes=()):
    return SimpleNamespace(
        get_pads=lambda: pads,
        get_tracks=lambda: tracks,
        get_vias=lambda: vias,
        get_zones=lambda: zones,
        get_shapes=lambda: shapes,
    )


def _pad(ident: str, x: float, y: float) -> Pad:
    pad = Pad()
    pad.id.value = ident
    pad.position = Vector2.from_xy_mm(x, y)
    pad.padstack.layers = [BoardLayer.BL_F_Cu]
    pad.padstack.copper_layers[0].size = Vector2.from_xy_mm(1.0, 0.6)
    return pad


def test_snapshot_excludes_only_identified_endpoints() -> None:
    start = _pad("start", 0, 0)
    end = _pad("end", 5, 0)
    other = _pad("other", 2.5, 0)
    obstacles = snapshot_route_obstacles(
        _board(pads=[start, end, other]),
        "F_Cu",
        frozenset({"start", "end"}),
    )
    assert len(obstacles) == 1
    assert isinstance(obstacles[0], CircleObstacle)
    assert obstacles[0].x_mm == 2.5
    assert obstacles[0].radius_mm >= 0.5


def test_track_capsule_is_conservatively_collected() -> None:
    track = Track()
    track.start = Vector2.from_xy_mm(1, 0)
    track.end = Vector2.from_xy_mm(3, 0)
    track.layer = BoardLayer.BL_F_Cu
    track.width = 300_000
    obstacles = snapshot_route_obstacles(_board(tracks=[track]), "F_Cu", frozenset())
    assert obstacles == (SegmentObstacle(1.0, 0.0, 3.0, 0.0, 0.15),)


def test_wrong_layer_obstacles_are_not_copied() -> None:
    pad = _pad("other", 2, 0)
    assert snapshot_route_obstacles(_board(pads=[pad]), "B_Cu", frozenset()) == ()


def test_unknown_copper_zones_fail_closed() -> None:
    zone = SimpleNamespace(layers=[BoardLayer.BL_F_Cu])
    with pytest.raises(RoutePlanningError, match="zone"):
        snapshot_route_obstacles(_board(zones=[zone]), "F_Cu", frozenset())


def test_unknown_copper_edge_shapes_fail_closed() -> None:
    edge = SimpleNamespace(layer=BoardLayer.BL_Edge_Cuts)
    with pytest.raises(RoutePlanningError, match="shape"):
        snapshot_route_obstacles(_board(shapes=[edge]), "F_Cu", frozenset())


def test_unreadable_board_fails_closed() -> None:
    with pytest.raises((RoutePlanningError, Exception)):
        snapshot_route_obstacles(SimpleNamespace(), "F_Cu", frozenset())


def test_native_rectangle_outline_is_four_obstacles() -> None:
    from kipy.board_types import BoardRectangle

    board_outline = BoardRectangle()
    board_outline.layer = BoardLayer.BL_Edge_Cuts
    board_outline.top_left = Vector2.from_xy_mm(0, 0)
    board_outline.bottom_right = Vector2.from_xy_mm(30, 20)
    start = _pad("start", 10, 10)
    end = _pad("end", 20, 10)
    result = snapshot_route_obstacles(
        _board(pads=[start, end], shapes=[board_outline]),
        "F_Cu",
        frozenset({"start", "end"}),
    )
    assert len(result) == 4
    assert all(isinstance(item, SegmentObstacle) for item in result)


def test_native_rectangle_rejects_endpoints_outside_outline() -> None:
    from kipy.board_types import BoardRectangle

    outline = BoardRectangle()
    outline.layer = BoardLayer.BL_Edge_Cuts
    outline.top_left = Vector2.from_xy_mm(0, 0)
    outline.bottom_right = Vector2.from_xy_mm(30, 20)
    with pytest.raises(RoutePlanningError, match="endpoints"):
        snapshot_route_obstacles(
            _board(pads=[_pad("start", 10, 10), _pad("end", 35, 10)], shapes=[outline]),
            "F_Cu",
            frozenset({"start", "end"}),
        )


def test_unknown_pad_layers_are_not_silent() -> None:
    pad = Pad()
    pad.id.value = "unknown-pad"
    pad.position = Vector2.from_xy_mm(2.5, 0)
    pad.padstack.layers = []
    with pytest.raises(RoutePlanningError, match="pad layer"):
        snapshot_route_obstacles(_board(pads=[pad]), "F_Cu", frozenset())


def test_unknown_via_layers_are_not_silent() -> None:
    from kipy.board_types import Via

    via = Via()
    via.position = Vector2.from_xy_mm(2.5, 0)
    via.padstack.layers = []
    with pytest.raises(RoutePlanningError, match="via layer"):
        snapshot_route_obstacles(_board(vias=[via]), "F_Cu", frozenset())


def test_required_board_outline_does_not_default_to_open_space() -> None:
    start = _pad("start", 10, 10)
    end = _pad("end", 20, 10)
    with pytest.raises(RoutePlanningError, match="board outline"):
        snapshot_route_obstacles(
            _board(pads=[start, end]),
            "F_Cu",
            frozenset({"start", "end"}),
            require_outline=True,
        )


def test_rectangle_outline_satisfies_required_boundary() -> None:
    from kipy.board_types import BoardRectangle

    outline = BoardRectangle()
    outline.layer = BoardLayer.BL_Edge_Cuts
    outline.top_left = Vector2.from_xy_mm(0, 0)
    outline.bottom_right = Vector2.from_xy_mm(30, 20)
    start = _pad("start", 10, 10)
    end = _pad("end", 20, 10)
    result = snapshot_route_obstacles(
        _board(pads=[start, end], shapes=[outline]),
        "F_Cu",
        frozenset({"start", "end"}),
        require_outline=True,
    )
    assert len(result) == 4

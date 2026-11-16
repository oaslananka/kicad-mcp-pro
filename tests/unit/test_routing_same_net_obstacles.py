"""Existing same-net copper must not prevent a safe new pad connection."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from kipy.board_types import Net, Pad, Track, Via
from kipy.geometry import Vector2
from kipy.proto.board.board_types_pb2 import BoardLayer

from kicad_mcp.pcb.routing_obstacle_snapshot import snapshot_route_obstacles
from kicad_mcp.routing.path_planner import CircleObstacle, RoutePlanningError, SegmentObstacle


def _net(name: str) -> Net:
    result = Net()
    result.name = name
    return result


def _pad(identity: str, name: str, x: float) -> Pad:
    pad = Pad()
    pad.id.value = identity
    pad.position = Vector2.from_xy_mm(x, 1)
    pad.padstack.layers = [BoardLayer.BL_F_Cu]
    pad.padstack.copper_layers[0].size = Vector2.from_xy_mm(0.5, 0.5)
    pad.net = _net(name)
    return pad


def _track(name: str, x: float) -> Track:
    track = Track()
    track.layer = BoardLayer.BL_F_Cu
    track.start = Vector2.from_xy_mm(x, 1)
    track.end = Vector2.from_xy_mm(x + 1, 1)
    track.width = 250_000
    track.net = _net(name)
    return track


def test_single_net_route_skips_existing_own_copper_but_not_foreign_copper() -> None:
    own = "USB_D_P"
    pads = [
        _pad("a", own, 0),
        _pad("b", own, 6),
        _pad("same", own, 1),
        _pad("other", "VBUS", 4),
    ]
    vias = []
    for name, x in ((own, 2), ("VBUS", 5)):
        via = Via()
        via.position = Vector2.from_xy_mm(x, 1)
        via.diameter = 600_000
        via.padstack.layers = [BoardLayer.BL_F_Cu]
        via.net = _net(name)
        vias.append(via)
    board = SimpleNamespace(
        get_pads=lambda: pads,
        get_tracks=lambda: [_track(own, 1), _track("GND", 3)],
        get_vias=lambda: vias,
        get_zones=lambda: [],
        get_shapes=lambda: [],
    )

    obstacles = snapshot_route_obstacles(board, "F_Cu", frozenset({"a", "b"}), routing_net=own)
    assert len(obstacles) == 3
    assert any(isinstance(item, SegmentObstacle) and item.x1_mm == 3 for item in obstacles)
    assert any(isinstance(item, CircleObstacle) and item.x_mm == 4 for item in obstacles)
    assert any(isinstance(item, CircleObstacle) and item.x_mm == 5 for item in obstacles)


def test_same_net_filter_cannot_override_endpoint_net_identity() -> None:
    board = SimpleNamespace(
        get_pads=lambda: [_pad("a", "VBUS", 0), _pad("b", "VBUS", 6)],
        get_tracks=lambda: [],
        get_vias=lambda: [],
        get_zones=lambda: [],
        get_shapes=lambda: [],
    )
    excluded = frozenset({"a", "b"})
    with pytest.raises(RoutePlanningError, match="net"):
        snapshot_route_obstacles(board, "F_Cu", excluded, routing_net="USB_D_P")

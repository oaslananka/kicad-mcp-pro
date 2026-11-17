"""Fine-pitch KiCad pads must be bounded by shape, not by their diagonal."""

from __future__ import annotations

from types import SimpleNamespace

from kipy.board_types import Pad
from kipy.geometry import Vector2
from kipy.proto.board.board_types_pb2 import BoardLayer, PadStackShape

from kicad_mcp.pcb.routing_obstacle_snapshot import snapshot_route_obstacles
from kicad_mcp.routing.path_planner import PolygonObstacle, _segment_clear


def test_adjacent_roundrect_pad_preserves_real_copper_clearance() -> None:
    adjacent = Pad()
    adjacent.id.value = "adjacent-foreign-net"
    adjacent.position = Vector2.from_xy_mm(0, 0.5)
    adjacent.padstack.layers = [BoardLayer.BL_F_Cu]
    copper = adjacent.padstack.copper_layers[0]
    copper.shape = PadStackShape.PSS_ROUNDRECT
    copper.size = Vector2.from_xy_mm(1.475, 0.3)

    board = SimpleNamespace(
        get_pads=lambda: [adjacent],
        get_tracks=lambda: [],
        get_vias=lambda: [],
        get_zones=lambda: [],
        get_shapes=lambda: [],
    )
    obstacles = snapshot_route_obstacles(board, "F_Cu", frozenset())
    assert len(obstacles) == 1
    assert isinstance(obstacles[0], PolygonObstacle)
    # 0.5 mm pad pitch, 0.30 mm pad height leaves 0.35 mm center
    # distance from the adjacent copper. Exactly 0.35 mm envelope is safe.
    assert _segment_clear((0, 0), (1, 0), obstacles, 0.35)
    assert not _segment_clear((0, 0.1), (1, 0.1), obstacles, 0.35)

"""Polygon keepouts and rounded board outlines must constrain route search."""

from __future__ import annotations

from types import SimpleNamespace

from kipy.board_types import (
    BoardArc,
    BoardLayer,
    BoardSegment,
    PolygonWithHoles,
    Zone,
    ZoneType,
)
from kipy.geometry import PolyLineNode, Vector2

from kicad_mcp.pcb.routing_obstacle_snapshot import snapshot_route_obstacles
from kicad_mcp.routing.path_planner import (
    BoardBoundary,
    PolygonObstacle,
    _segment_clear,
    plan_hv45_path,
)

_ENDPOINT_IDS = frozenset({"start", "end"})


def _polygon(points: tuple[tuple[float, float], ...]) -> PolygonWithHoles:
    result = PolygonWithHoles()
    for x_mm, y_mm in points:
        result.outline.append(PolyLineNode.from_point(Vector2.from_xy_mm(x_mm, y_mm)))
    result.outline.closed = True
    return result


def _segment(start: tuple[float, float], end: tuple[float, float]) -> BoardSegment:
    shape = BoardSegment()
    shape.layer = BoardLayer.BL_Edge_Cuts
    shape.start = Vector2.from_xy_mm(*start)
    shape.end = Vector2.from_xy_mm(*end)
    return shape


def _arc(
    start: tuple[float, float],
    mid: tuple[float, float],
    end: tuple[float, float],
) -> BoardArc:
    shape = BoardArc()
    shape.layer = BoardLayer.BL_Edge_Cuts
    shape.start = Vector2.from_xy_mm(*start)
    shape.mid = Vector2.from_xy_mm(*mid)
    shape.end = Vector2.from_xy_mm(*end)
    return shape


def _rounded_rectangle() -> list[BoardSegment | BoardArc]:
    return [
        _segment((2, 0), (28, 0)),
        _arc((28, 0), (29.41421356, 0.58578644), (30, 2)),
        _segment((30, 2), (30, 18)),
        _arc((30, 18), (29.41421356, 19.41421356), (28, 20)),
        _segment((28, 20), (2, 20)),
        _arc((2, 20), (0.58578644, 19.41421356), (0, 18)),
        _segment((0, 18), (0, 2)),
        _arc((0, 2), (0.58578644, 0.58578644), (2, 0)),
    ]


def _rule_area(
    points: tuple[tuple[float, float], ...],
    *,
    keepout_tracks: bool = True,
    keepout_vias: bool = True,
) -> Zone:
    zone = Zone()
    zone.type = ZoneType.ZT_RULE_AREA
    zone.layers = [BoardLayer.BL_F_Cu]
    zone.outline = _polygon(points)
    zone.proto.rule_area_settings.keepout_tracks = keepout_tracks
    zone.proto.rule_area_settings.keepout_vias = keepout_vias
    return zone


class _Board:
    def __init__(self, shapes: list[object], zones: list[Zone]) -> None:
        self._shapes = shapes
        self._zones = zones
        self._pads = [
            SimpleNamespace(
                id=SimpleNamespace(value="start"),
                position=Vector2.from_xy_mm(4, 10),
            ),
            SimpleNamespace(
                id=SimpleNamespace(value="end"),
                position=Vector2.from_xy_mm(26, 10),
            ),
        ]

    def get_shapes(self) -> list[object]:
        return self._shapes

    def get_zones(self) -> list[Zone]:
        return self._zones

    def get_tracks(self) -> list[object]:
        return []

    def get_vias(self) -> list[object]:
        return []

    def get_pads(self) -> list[object]:
        return self._pads


def _snapshot(board: _Board, *, for_via: bool = False):
    return snapshot_route_obstacles(
        board,
        "F_Cu",
        _ENDPOINT_IDS,
        require_outline=True,
        expected_endpoint_count=2,
        for_via=for_via,
    )


def test_rounded_board_outline_becomes_a_conservative_boundary() -> None:
    obstacles = _snapshot(_Board(_rounded_rectangle(), []))

    boundaries = [item for item in obstacles if isinstance(item, BoardBoundary)]
    assert len(boundaries) == 1
    assert len(boundaries[0].vertices) >= 12


def test_rule_area_keepout_blocks_crossing_and_allows_a_safe_detour() -> None:
    keepout = _rule_area(((12, 7), (18, 7), (18, 13), (12, 13)))
    obstacles = _snapshot(_Board(_rounded_rectangle(), [keepout]))

    boundary = next(item for item in obstacles if isinstance(item, BoardBoundary))
    polygon = next(item for item in obstacles if isinstance(item, PolygonObstacle))
    assert not _segment_clear((4, 10), (26, 10), (polygon,), 0.3)

    path = plan_hv45_path(
        (4, 10),
        (26, 10),
        obstacles,
        track_width_mm=0.2,
        clearance_mm=0.2,
        grid_mm=0.5,
        margin_mm=5.0,
        max_nodes=20_000,
    )
    assert len(path) > 2
    assert all(_segment_clear(a, b, (boundary,), 0.3) for a, b in zip(path, path[1:], strict=False))
    assert all(_segment_clear(a, b, (polygon,), 0.3) for a, b in zip(path, path[1:], strict=False))


def test_rule_area_that_only_blocks_vias_does_not_block_tracks() -> None:
    zone = _rule_area(
        ((12, 7), (18, 7), (18, 13), (12, 13)),
        keepout_tracks=False,
        keepout_vias=True,
    )
    board = _Board(_rounded_rectangle(), [zone])

    track_obstacles = _snapshot(board)
    via_obstacles = _snapshot(board, for_via=True)

    assert not any(isinstance(item, PolygonObstacle) for item in track_obstacles)
    assert any(isinstance(item, PolygonObstacle) for item in via_obstacles)

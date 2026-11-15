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
    _checked_args = (_board(zones=[zone]), "F_Cu", frozenset())
    with pytest.raises(RoutePlanningError, match="zone"):
        snapshot_route_obstacles(*_checked_args)


def test_unknown_copper_edge_shapes_fail_closed() -> None:
    edge = SimpleNamespace(layer=BoardLayer.BL_Edge_Cuts)
    _checked_args = (_board(shapes=[edge]), "F_Cu", frozenset())
    with pytest.raises(RoutePlanningError, match="shape"):
        snapshot_route_obstacles(*_checked_args)


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
    _checked_args = (
        _board(pads=[_pad("start", 10, 10), _pad("end", 35, 10)], shapes=[outline]),
        "F_Cu",
        frozenset({"start", "end"}),
    )
    with pytest.raises(RoutePlanningError, match="endpoints"):
        snapshot_route_obstacles(*_checked_args)


def test_unknown_pad_layers_are_not_silent() -> None:
    pad = Pad()
    pad.id.value = "unknown-pad"
    pad.position = Vector2.from_xy_mm(2.5, 0)
    pad.padstack.layers = []
    _checked_args = (_board(pads=[pad]), "F_Cu", frozenset())
    with pytest.raises(RoutePlanningError, match="pad layer"):
        snapshot_route_obstacles(*_checked_args)


def test_unknown_via_layers_are_not_silent() -> None:
    from kipy.board_types import Via

    via = Via()
    via.position = Vector2.from_xy_mm(2.5, 0)
    via.padstack.layers = []
    _checked_args = (_board(vias=[via]), "F_Cu", frozenset())
    with pytest.raises(RoutePlanningError, match="via layer"):
        snapshot_route_obstacles(*_checked_args)


def test_required_board_outline_does_not_default_to_open_space() -> None:
    start = _pad("start", 10, 10)
    end = _pad("end", 20, 10)
    _checked_args = (_board(pads=[start, end]), "F_Cu", frozenset({"start", "end"}))
    _checked_kwargs = {"require_outline": True}
    with pytest.raises(RoutePlanningError, match="board outline"):
        snapshot_route_obstacles(*_checked_args, **_checked_kwargs)


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


def _edge_line(a: tuple[float, float], b: tuple[float, float]):
    from kipy.board_types import BoardSegment

    line = BoardSegment()
    line.layer = BoardLayer.BL_Edge_Cuts
    line.start = Vector2.from_xy_mm(*a)
    line.end = Vector2.from_xy_mm(*b)
    return line


def test_four_separate_edge_segments_are_a_valid_closed_rectangle() -> None:
    edges = [
        _edge_line((30, 0), (0, 0)),
        _edge_line((30, 20), (30, 0)),
        _edge_line((0, 20), (30, 20)),
        _edge_line((0, 0), (0, 20)),
    ]
    start = _pad("start", 10, 10)
    end = _pad("end", 20, 10)
    barriers = snapshot_route_obstacles(
        _board(pads=[start, end], shapes=edges),
        "F_Cu",
        frozenset({"start", "end"}),
        require_outline=True,
    )
    assert len(barriers) == 4
    assert all(isinstance(item, SegmentObstacle) for item in barriers)


def test_three_edge_segments_are_not_a_closed_board_outline() -> None:
    edges = [
        _edge_line((0, 0), (30, 0)),
        _edge_line((30, 0), (30, 20)),
        _edge_line((30, 20), (0, 20)),
    ]
    _checked_args = (
        _board(pads=[_pad("start", 10, 10), _pad("end", 20, 10)], shapes=edges),
        "F_Cu",
        frozenset({"start", "end"}),
    )
    _checked_kwargs = {"require_outline": True}
    with pytest.raises(RoutePlanningError, match="outline|edge"):
        snapshot_route_obstacles(*_checked_args, **_checked_kwargs)


def test_duplicate_edge_and_diagonal_outlines_are_refused() -> None:
    edges = [
        _edge_line((0, 0), (30, 0)),
        _edge_line((0, 0), (30, 0)),
        _edge_line((30, 0), (30, 20)),
        _edge_line((30, 20), (0, 0)),
    ]
    _checked_args = (
        _board(pads=[_pad("start", 10, 10), _pad("end", 20, 10)], shapes=edges),
        "F_Cu",
        frozenset({"start", "end"}),
    )
    _checked_kwargs = {"require_outline": True}
    with pytest.raises(RoutePlanningError, match="outline|edge"):
        snapshot_route_obstacles(*_checked_args, **_checked_kwargs)


def test_closed_line_outline_rejects_endpoints_outside() -> None:
    outline = [
        _edge_line((0, 0), (30, 0)),
        _edge_line((30, 0), (30, 20)),
        _edge_line((30, 20), (0, 20)),
        _edge_line((0, 20), (0, 0)),
    ]
    _checked_args = (
        _board(pads=[_pad("start", 10, 10), _pad("end", 40, 10)], shapes=outline),
        "F_Cu",
        frozenset({"start", "end"}),
    )
    _checked_kwargs = {"require_outline": True}
    with pytest.raises(RoutePlanningError, match="endpoints"):
        snapshot_route_obstacles(*_checked_args, **_checked_kwargs)


def test_mixed_rectangle_and_board_line_outlines_are_refused() -> None:
    from kipy.board_types import BoardRectangle

    box = BoardRectangle()
    box.layer = BoardLayer.BL_Edge_Cuts
    box.top_left = Vector2.from_xy_mm(0, 0)
    box.bottom_right = Vector2.from_xy_mm(30, 20)
    _checked_args = (
        _board(
            pads=[_pad("start", 10, 10), _pad("end", 20, 10)],
            shapes=[box, _edge_line((0, 0), (30, 0))],
        ),
        "F_Cu",
        frozenset({"start", "end"}),
    )
    _checked_kwargs = {"require_outline": True}
    with pytest.raises(RoutePlanningError, match="Mixed|outline"):
        snapshot_route_obstacles(*_checked_args, **_checked_kwargs)


def test_paired_outline_requires_all_four_pad_identities() -> None:
    from kipy.board_types import BoardRectangle

    rect = BoardRectangle()
    rect.layer = BoardLayer.BL_Edge_Cuts
    rect.top_left = Vector2.from_xy_mm(0, 0)
    rect.bottom_right = Vector2.from_xy_mm(30, 20)
    pair = [
        _pad("p1", 10, 10),
        _pad("p2", 20, 10),
        _pad("n1", 10, 10.75),
        _pad("n2", 20, 10.75),
    ]
    third_party = _pad("unrelated", 15, 10.5)
    obstacles = snapshot_route_obstacles(
        _board(pads=[*pair, third_party], shapes=[rect]),
        "F_Cu",
        frozenset({"p1", "p2", "n1", "n2"}),
        expected_endpoint_count=4,
        require_outline=True,
    )
    assert len(obstacles) == 5
    assert isinstance(obstacles[-1], CircleObstacle)

    _checked_args = (
        _board(pads=[*pair, third_party], shapes=[rect]),
        "F_Cu",
        frozenset({"p1", "p2", "n1"}),
    )
    _checked_kwargs = {"expected_endpoint_count": 4, "require_outline": True}
    with pytest.raises(RoutePlanningError, match="endpoints"):
        snapshot_route_obstacles(*_checked_args, **_checked_kwargs)

    _checked_args = (
        _board(pads=[*pair, third_party], shapes=[rect]),
        "F_Cu",
        frozenset({"p1", "p2", "n1", "n2"}),
    )
    _checked_kwargs = {"require_outline": True}
    with pytest.raises(RoutePlanningError, match="endpoints"):
        snapshot_route_obstacles(*_checked_args, **_checked_kwargs)


def test_one_via_uses_one_endpoint_per_layer_without_disabling_outline_checks() -> None:
    from kipy.board_types import BoardRectangle

    outline = BoardRectangle()
    outline.layer = BoardLayer.BL_Edge_Cuts
    outline.top_left = Vector2.from_xy_mm(0, 0)
    outline.bottom_right = Vector2.from_xy_mm(30, 20)
    pad = _pad("start-only", 10, 10)
    result = snapshot_route_obstacles(
        _board(pads=[pad], shapes=[outline]),
        "F_Cu",
        frozenset({"start-only"}),
        require_outline=True,
        expected_endpoint_count=1,
    )
    assert len(result) == 4
    _checked_args = (_board(pads=[pad], shapes=[outline]), "F_Cu", frozenset({"start-only"}))
    _checked_kwargs = {"require_outline": True}
    with pytest.raises(RoutePlanningError, match="endpoints"):
        snapshot_route_obstacles(*_checked_args, **_checked_kwargs)


@pytest.mark.parametrize("layer", ["F_SilkS", "Edge_Cuts", "B_Mask"])
def test_route_snapshot_rejects_non_copper_layer_even_on_empty_board(layer: str) -> None:
    _checked_args = (_board(), layer, frozenset())
    with pytest.raises(RoutePlanningError, match="copper layer"):
        snapshot_route_obstacles(*_checked_args)


def test_snapshot_rejects_pad_without_stable_identity_or_padstack() -> None:
    pad = _pad("fixture", 10, 10)
    pad.id.value = ""
    _checked_args = (_board(pads=[pad]), "F_Cu", frozenset())
    with pytest.raises(RoutePlanningError, match="stable native identity"):
        snapshot_route_obstacles(*_checked_args)
    malformed = SimpleNamespace(id=SimpleNamespace(value="fixture"), padstack=None)
    _checked_args = (_board(pads=[malformed]), "F_Cu", frozenset())
    with pytest.raises(RoutePlanningError, match="Pad stack unavailable"):
        snapshot_route_obstacles(*_checked_args)


def test_zero_dimension_pad_fails_closed_and_offset_expands_envelope() -> None:
    pad = _pad("other", 12, 10)
    pad.padstack.copper_layers[0].size = Vector2.from_xy_mm(0, 1)
    _checked_args = (_board(pads=[pad]), "F_Cu", frozenset())
    with pytest.raises(RoutePlanningError, match="usable dimensions"):
        snapshot_route_obstacles(*_checked_args)

    pad.padstack.copper_layers[0].size = Vector2.from_xy_mm(1, 1)
    centered = snapshot_route_obstacles(_board(pads=[pad]), "F_Cu", frozenset())[0]
    pad.padstack.copper_layers[0].offset = Vector2.from_xy_mm(0.2, 0.3)
    shifted = snapshot_route_obstacles(_board(pads=[pad]), "F_Cu", frozenset())[0]
    assert isinstance(centered, CircleObstacle)
    assert isinstance(shifted, CircleObstacle)
    assert shifted.radius_mm > centered.radius_mm


@pytest.mark.parametrize("width", [0, -100_000])
def test_native_track_with_nonpositive_width_is_never_ignored(width: int) -> None:
    track = Track()
    track.start = Vector2.from_xy_mm(1, 1)
    track.end = Vector2.from_xy_mm(2, 1)
    track.layer = BoardLayer.BL_F_Cu
    track.width = width
    _checked_args = (_board(tracks=[track]), "F_Cu", frozenset())
    with pytest.raises(RoutePlanningError, match="invalid width"):
        snapshot_route_obstacles(*_checked_args)


def test_native_via_is_an_obstacle_on_copper_but_ignored_on_other_layers() -> None:
    from kipy.board_types import Via

    via = Via()
    via.position = Vector2.from_xy_mm(15, 10)
    via.diameter = 600_000
    via.padstack.layers = [BoardLayer.BL_F_Cu]
    front = snapshot_route_obstacles(_board(vias=[via]), "F_Cu", frozenset())
    back = snapshot_route_obstacles(_board(vias=[via]), "B_Cu", frozenset())
    assert back == ()
    assert front == (CircleObstacle(15, 10, 0.3),)


def test_zero_via_diameter_must_be_rejected() -> None:
    from kipy.board_types import Via

    via = Via()
    via.position = Vector2.from_xy_mm(15, 10)
    via.diameter = 0
    via.padstack.layers = [BoardLayer.BL_F_Cu]
    _checked_args = (_board(vias=[via]), "F_Cu", frozenset())
    with pytest.raises(RoutePlanningError, match="diameter"):
        snapshot_route_obstacles(*_checked_args)


def test_missing_via_stack_fails_closed() -> None:
    via = SimpleNamespace(position=Vector2.from_xy_mm(15, 10), padstack=None)
    _checked_args = (_board(vias=[via]), "F_Cu", frozenset())
    with pytest.raises(RoutePlanningError, match="Via stack unavailable"):
        snapshot_route_obstacles(*_checked_args)


def test_copper_zone_on_other_layer_not_treated_as_unbounded_obstacle() -> None:
    foreign = SimpleNamespace(layers=[BoardLayer.BL_B_Cu])
    assert snapshot_route_obstacles(_board(zones=[foreign]), "F_Cu", frozenset()) == ()


def test_unknown_zone_layer_membership_refuses_planning() -> None:
    unknown = SimpleNamespace(layers=None)
    _checked_args = (_board(zones=[unknown]), "F_Cu", frozenset())
    with pytest.raises(RoutePlanningError, match="zone"):
        snapshot_route_obstacles(*_checked_args)


def test_unrelated_fabrication_shapes_are_not_copper_obstacles() -> None:
    other_layer = SimpleNamespace(layer=BoardLayer.BL_F_SilkS)
    assert snapshot_route_obstacles(_board(shapes=[other_layer]), "F_Cu", frozenset()) == ()


def _outline(x1: float, y1: float, x2: float, y2: float):
    from kipy.board_types import BoardRectangle

    rect = BoardRectangle()
    rect.layer = BoardLayer.BL_Edge_Cuts
    rect.top_left = Vector2.from_xy_mm(x1, y1)
    rect.bottom_right = Vector2.from_xy_mm(x2, y2)
    return rect


@pytest.mark.parametrize(
    ("outline", "message"),
    [
        (_outline(30, 20, 0, 0), "Invalid board edge rectangle"),
        (_outline(0, 0, 0, 20), "Invalid board edge rectangle"),
    ],
)
def test_nonpositive_or_inverted_rectangular_outline_fails_closed(
    outline: object, message: str
) -> None:
    _checked_args = (_board(shapes=[outline]), "F_Cu", frozenset())
    with pytest.raises(RoutePlanningError, match=message):
        snapshot_route_obstacles(*_checked_args)


def test_multiple_rectangles_have_no_unambiguous_board_interior() -> None:
    _checked_args = (
        _board(shapes=[_outline(0, 0, 30, 20), _outline(2, 2, 25, 15)]),
        "F_Cu",
        frozenset(),
    )
    with pytest.raises(RoutePlanningError, match="Multiple board edge"):
        snapshot_route_obstacles(*_checked_args)


def test_zero_length_board_edge_segment_is_not_accepted() -> None:
    edge = _edge_line((0, 0), (0, 0))
    _checked_args = (_board(shapes=[edge]), "F_Cu", frozenset())
    with pytest.raises(RoutePlanningError, match="segment geometry"):
        snapshot_route_obstacles(*_checked_args)


def test_outline_requires_bounded_endpoint_count() -> None:
    pads = [_pad("a", 10, 10), _pad("b", 20, 10)]
    _checked_args = (
        _board(pads=pads, shapes=[_outline(0, 0, 30, 20)]),
        "F_Cu",
        frozenset({"a", "b"}),
    )
    _checked_kwargs = {"expected_endpoint_count": 3, "require_outline": True}
    with pytest.raises(RoutePlanningError, match="endpoints"):
        snapshot_route_obstacles(*_checked_args, **_checked_kwargs)

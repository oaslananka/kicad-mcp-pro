"""Bounded, deterministic, geometry-only routing planner tests."""

from __future__ import annotations

from math import hypot

import pytest

from kicad_mcp.routing.path_planner import (
    CircleObstacle,
    RoutePlanningError,
    SegmentObstacle,
    is_hv45_path,
    plan_hv45_path,
)


def test_clear_direct_route_is_one_segment() -> None:
    assert plan_hv45_path((0.0, 0.0), (5.0, 0.0), ()) == (
        (0.0, 0.0),
        (5.0, 0.0),
    )


def test_obstacle_forces_hv45_detour_without_collisions() -> None:
    obstacle = CircleObstacle(2.5, 0.0, 0.7)
    path = plan_hv45_path(
        (0.0, 0.0),
        (5.0, 0.0),
        (obstacle,),
        track_width_mm=0.25,
        clearance_mm=0.2,
        grid_mm=0.25,
        margin_mm=2.0,
    )
    assert path[0] == (0.0, 0.0)
    assert path[-1] == (5.0, 0.0)
    assert is_hv45_path(path)
    assert len(path) > 2
    # The full copper stroke must clear the obstacle, not just the waypoints.
    for a, b in zip(path, path[1:], strict=False):
        dx, dy = b[0] - a[0], b[1] - a[1]
        projection = min(1.0, max(0.0, ((2.5 - a[0]) * dx - a[1] * dy) / (dx * dx + dy * dy)))
        distance = hypot(a[0] + projection * dx - 2.5, a[1] + projection * dy)
        assert distance >= obstacle.radius_mm + 0.25 / 2 + 0.2 - 1e-8
    assert path == plan_hv45_path(
        (0.0, 0.0),
        (5.0, 0.0),
        (obstacle,),
        track_width_mm=0.25,
        clearance_mm=0.2,
        grid_mm=0.25,
        margin_mm=2.0,
    )


def test_parallel_existing_track_is_avoided() -> None:
    obstacle = SegmentObstacle(1.0, -0.5, 3.0, 0.5, 0.15)
    path = plan_hv45_path(
        (0.0, 0.0),
        (4.0, 0.0),
        (obstacle,),
        track_width_mm=0.2,
        clearance_mm=0.2,
        grid_mm=0.25,
        margin_mm=2.0,
    )
    assert is_hv45_path(path)
    assert len(path) > 2


@pytest.mark.parametrize(
    ("source", "target"),
    [
        ((1.0, 1.0), (1.0, 1.0)),
        ((float("nan"), 0.0), (4.0, 0.0)),
    ],
)
def test_bad_geometry_fails_closed(
    source: tuple[float, float], target: tuple[float, float]
) -> None:
    with pytest.raises(RoutePlanningError):
        plan_hv45_path(source, target, ())


def test_start_inside_blocker_is_not_plannable() -> None:
    _checked_args = ((0.0, 0.0), (5.0, 0.0), (CircleObstacle(0.0, 0.0, 1.0),))
    with pytest.raises(RoutePlanningError, match="obstacle"):
        plan_hv45_path(*_checked_args)


def test_bounded_search_never_guesses_a_route() -> None:
    _checked_args = ((0.0, 0.0), (5.0, 0.0), (CircleObstacle(2.5, 0.0, 0.8),))
    _checked_kwargs = {"max_nodes": 2, "grid_mm": 0.25, "margin_mm": 2.0}
    with pytest.raises(RoutePlanningError, match="budget|route"):
        plan_hv45_path(*_checked_args, **_checked_kwargs)


def test_unsupported_width_or_clearance_refused() -> None:
    with pytest.raises(RoutePlanningError):
        plan_hv45_path((0.0, 0.0), (3.0, 0.0), (), track_width_mm=-0.3)
    with pytest.raises(RoutePlanningError):
        plan_hv45_path((0.0, 0.0), (3.0, 0.0), (), clearance_mm=-0.1)


def test_reproducible_obstacle_fuzz_never_returns_collision() -> None:
    from kicad_mcp.routing.path_planner import _segment_clear

    for shift in range(-4, 5):
        obstacles = (
            CircleObstacle(2.0, shift * 0.20, 0.60),
            SegmentObstacle(3.0, 0.5, 3.0, 1.5, 0.10),
        )
        try:
            points = plan_hv45_path(
                (0.0, 0.0),
                (5.0, 0.0),
                obstacles,
                grid_mm=0.25,
                margin_mm=2.0,
                max_nodes=4000,
            )
        except RoutePlanningError:
            continue  # A bounded refusal is safer than speculative geometry.
        assert is_hv45_path(points)
        for a, b in zip(points, points[1:], strict=False):
            assert _segment_clear(a, b, obstacles, 0.125 + 0.20)

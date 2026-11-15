"""Two USB lanes must remain a matched pair around another-net copper."""

from __future__ import annotations

import pytest

from kicad_mcp.routing.path_planner import (
    CircleObstacle,
    RoutePlanningError,
    SegmentObstacle,
    _segment_clear,
)


def _plan(obstacles: tuple[CircleObstacle | SegmentObstacle, ...]):
    from kicad_mcp.routing.differential_pair_candidate import plan_coupled_hv45_pair

    return plan_coupled_hv45_pair(
        plus_start=(0.0, 0.0),
        plus_end=(8.0, 0.0),
        minus_start=(0.0, 0.75),
        minus_end=(8.0, 0.75),
        obstacles=obstacles,
        layer="F_Cu",
        net_plus="USB_D_P",
        net_minus="USB_D_N",
        width_mm=0.25,
        gap_mm=0.5,
        clearance_mm=0.2,
        max_skew_mm=0.1,
    )


def test_obstacle_forces_matched_dogleg_without_new_copper_intersections() -> None:
    obstacle = CircleObstacle(4.0, 0.375, 0.5)
    plus, minus, measurements = _plan((obstacle,))
    assert len(plus) > 1 and len(minus) > 1
    assert plus[0].x1_mm == 0 and plus[0].y1_mm == 0
    assert minus[0].x1_mm == 0 and minus[0].y1_mm == 0.75
    assert plus[-1].x2_mm == 8 and plus[-1].y2_mm == 0
    assert minus[-1].x2_mm == 8 and minus[-1].y2_mm == 0.75
    assert measurements["skewMm"] <= 0.1
    assert measurements["lengthPlusMm"] > 8.0
    assert measurements["lengthMinusMm"] > 8.0
    assert measurements["minCopperGapMm"] >= 0.5 - 1e-5
    for spec in (*plus, *minus):
        a = (spec.x1_mm, spec.y1_mm)
        b = (spec.x2_mm, spec.y2_mm)
        assert _segment_clear(a, b, (obstacle,), 0.125 + 0.2)


def test_coupled_route_is_repeatable_and_uses_one_copper_layer() -> None:
    obstacle = SegmentObstacle(3.75, 0.2, 4.25, 0.55, 0.25)
    plus, minus, measurements = _plan((obstacle,))
    assert (plus, minus, measurements) == _plan((obstacle,))
    assert all(item.layer == "F_Cu" for item in (*plus, *minus))
    assert all(item.net_name == "USB_D_P" for item in plus)
    assert all(item.net_name == "USB_D_N" for item in minus)
    assert measurements["minCopperGapMm"] >= 0.5 - 1e-5


@pytest.mark.parametrize(
    ("minus_start", "minus_end"),
    [
        ((0.0, 0.40), (8.0, 0.40)),
        ((0.0, 0.75), (8.0, 1.25)),
        ((0.0, 0.75), (7.9, 0.75)),
    ],
)
def test_rejects_unsafe_pad_spacing_before_search(
    minus_start: tuple[float, float],
    minus_end: tuple[float, float],
) -> None:
    from kicad_mcp.routing.differential_pair_candidate import plan_coupled_hv45_pair

    with pytest.raises(RoutePlanningError, match="aligned|spacing|offset"):
        plan_coupled_hv45_pair(
            plus_start=(0, 0),
            plus_end=(8, 0),
            minus_start=minus_start,
            minus_end=minus_end,
            obstacles=(),
            layer="F_Cu",
            net_plus="USB_D_P",
            net_minus="USB_D_N",
            width_mm=0.25,
            gap_mm=0.5,
            clearance_mm=0.2,
            max_skew_mm=0.1,
        )


def test_blocked_departure_refuses_instead_of_crossing_a_pad() -> None:
    with pytest.raises(RoutePlanningError, match="obstacle|route|clear"):
        _plan((CircleObstacle(0.8, 0.375, 0.85),))

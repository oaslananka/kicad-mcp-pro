"""A through-via must respect via-only keepout zones on both outer layers."""

from __future__ import annotations

import pytest

from kicad_mcp.routing.path_planner import PolygonObstacle, RoutePlanningError
from kicad_mcp.routing.through_via_planner import plan_one_through_via


def _plan(via_obstacles: tuple[PolygonObstacle, ...]):
    return plan_one_through_via(
        (0, 0),
        (10, 0),
        front_obstacles=(),
        back_obstacles=(),
        front_via_obstacles=via_obstacles,
        back_via_obstacles=via_obstacles,
        start_layer="F_Cu",
        end_layer="B_Cu",
        net_name="USB_D_P",
        width_mm=0.25,
        clearance_mm=0.2,
        diameter_mm=0.8,
        drill_mm=0.4,
    )


def test_via_only_keepout_rejects_all_transition_sites() -> None:
    forbidden = PolygonObstacle(((2, -1), (8, -1), (8, 1), (2, 1)))
    with pytest.raises(RoutePlanningError, match="collision-free|via"):
        _plan((forbidden,))


def test_via_only_keepout_steers_via_outside_prohibited_region() -> None:
    forbidden = PolygonObstacle(((4, -1), (6, -1), (6, 1), (4, 1)))
    tracks, via, geometry = _plan((forbidden,))
    assert len(tracks) == 2
    assert geometry["viaCount"] == 1
    assert via.x_mm in (3.5, 6.5, 2.5, 7.5)

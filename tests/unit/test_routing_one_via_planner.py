"""One through-via is allowed only for a safe front/back topology."""

from __future__ import annotations

import pytest

from kicad_mcp.routing.path_planner import CircleObstacle, RoutePlanningError


def _plan(
    *,
    front: tuple[CircleObstacle, ...] = (),
    back: tuple[CircleObstacle, ...] = (),
    endpoint: tuple[float, float] = (19.05, 10),
):
    from kicad_mcp.routing.through_via_planner import plan_one_through_via

    return plan_one_through_via(
        (10.95, 10),
        endpoint,
        front_obstacles=front,
        back_obstacles=back,
        start_layer="F_Cu",
        end_layer="B_Cu",
        net_name="MID",
        width_mm=0.25,
        clearance_mm=0.2,
        diameter_mm=0.8,
        drill_mm=0.4,
    )


def test_front_back_midpoint_has_two_tracks_and_one_through_via() -> None:
    tracks, via, evidence = _plan()
    assert [t.layer for t in tracks] == ["F_Cu", "B_Cu"]
    assert via.x_mm == pytest.approx(15)
    assert via.y_mm == 10
    assert via.net_name == "MID"
    assert tracks[0].x2_mm == via.x_mm == tracks[1].x1_mm
    assert evidence["viaCount"] == 1
    assert evidence["viaCostMm"] > 0
    assert evidence["totalTraceLengthMm"] == pytest.approx(8.1)


def test_nearby_foreign_net_copper_on_both_layers_changes_via_position() -> None:
    tracks, via, _ = _plan(front=(CircleObstacle(15, 10, 0.35),))
    assert abs(via.x_mm - 15) > 0.5
    assert tracks[0].x2_mm == via.x_mm
    assert tracks[1].x1_mm == via.x_mm


def test_blocked_via_positions_refuse_without_inventing_tracks() -> None:
    _checked_kwargs = {"front": (CircleObstacle(15, 10, 10),)}
    with pytest.raises(RoutePlanningError, match="via|transition|obstacle"):
        _plan(**_checked_kwargs)


@pytest.mark.parametrize(
    "target",
    [(19.05, 11), (10.95, 10), (100, 10)],
)
def test_out_of_scope_geometry_is_rejected(target: tuple[float, float]) -> None:
    with pytest.raises(RoutePlanningError, match="aligned|extent|length|same"):
        _plan(endpoint=target)


def test_invalid_diameter_and_layer_are_refused() -> None:
    from kicad_mcp.routing.through_via_planner import plan_one_through_via

    with pytest.raises(RoutePlanningError):
        plan_one_through_via(
            (10, 10),
            (20, 10),
            front_obstacles=(),
            back_obstacles=(),
            start_layer="F_Cu",
            end_layer="In1_Cu",
            net_name="MID",
            width_mm=0.25,
            clearance_mm=0.2,
            diameter_mm=0.8,
            drill_mm=0.4,
        )

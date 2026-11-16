"""Bounded H/V/45 differential fanout for different connector and lane pitches.

Pure geometry; no KiCad access, no physical impedance or manufacturing approval.
"""

from __future__ import annotations

import pytest

from kicad_mcp.routing.differential_pair_candidate import plan_coupled_hv45_pair
from kicad_mcp.routing.path_planner import CircleObstacle, RoutePlanningError


def _args() -> dict[str, object]:
    return {
        "plus_start": (121.11, 104.575),
        "plus_end": (124.75, 104.595),
        "minus_start": (121.11, 105.425),
        "minus_end": (124.75, 105.455),
        "obstacles": (),
        "layer": "F_Cu",
        "net_plus": "USB_CON_P",
        "net_minus": "USB_CON_N",
        "width_mm": 0.3,
        "gap_mm": 0.25,
        "clearance_mm": 0.2,
        "max_skew_mm": 0.1,
    }


def _plan(**overrides: object):
    return plan_coupled_hv45_pair(**(_args() | overrides))


def test_real_connector_pitch_fanout_is_matched_and_deterministic() -> None:
    plus, minus, geometry = _plan()
    assert len(plus) == len(minus) == 5
    assert geometry["skewMm"] <= 0.1
    assert geometry["minCopperGapMm"] >= 0.25 - 1e-5
    assert geometry["lengthPlusMm"] > 3.64
    assert plus[0].x1_mm == minus[0].x1_mm == 121.11
    assert plus[0].y1_mm == 104.575
    assert minus[0].y1_mm == 105.425
    assert plus[-1].x2_mm == minus[-1].x2_mm == 124.75
    assert plus[-1].y2_mm == 104.595
    assert minus[-1].y2_mm == 105.455
    assert _plan() == (plus, minus, geometry)
    for lane, net in ((plus, "USB_CON_P"), (minus, "USB_CON_N")):
        assert all(spec.layer == "F_Cu" and spec.net_name == net for spec in lane)
        for spec in lane:
            dx, dy = abs(spec.x2_mm - spec.x1_mm), abs(spec.y2_mm - spec.y1_mm)
            assert dx > 0 or dy > 0
            assert min(dx, dy) < 1e-6 or abs(dx - dy) < 1e-6


def test_reversed_horizontal_direction_keeps_pair_and_endpoints() -> None:
    plus, minus, geometry = _plan(
        plus_start=(124.75, 104.575),
        plus_end=(121.11, 104.595),
        minus_start=(124.75, 105.425),
        minus_end=(121.11, 105.455),
    )
    assert len(plus) == len(minus) == 5
    assert plus[0].x1_mm == 124.75
    assert plus[-1].x2_mm == 121.11
    assert minus[0].x1_mm == 124.75
    assert minus[-1].x2_mm == 121.11
    assert geometry["minCopperGapMm"] >= 0.25 - 1e-5


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"obstacles": (CircleObstacle(122.0, 105.0125, 0.4),)}, "collides|obstacle"),
        ({"plus_end": (122.11, 104.595), "minus_end": (122.11, 105.455)}, "aligned|spacing"),
        ({"plus_end": (144.75, 104.595), "minus_end": (144.75, 105.455)}, "aligned|spacing"),
        ({"minus_end": (124.75, 104.0)}, "aligned|spacing"),
        ({"minus_end": (124.75, 105.8)}, "aligned|spacing"),
        ({"minus_start": (121.11, 104.975), "minus_end": (124.75, 104.995)}, "aligned|spacing"),
        ({"minus_start": (121.21, 105.425)}, "aligned|spacing"),
        ({"net_minus": "USB_CON_P"}, "matched"),
        ({"gap_mm": 0.0}, "dimensions"),
    ],
)
def test_fanout_refuses_unqualified_geometry_and_foreign_obstacles(
    overrides: dict[str, object], reason: str
) -> None:
    with pytest.raises(RoutePlanningError, match=reason):
        _plan(**overrides)

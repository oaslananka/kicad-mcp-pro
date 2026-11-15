"""The narrow straight-pair route must preserve copper gap and length match."""

from __future__ import annotations

import pytest

from kicad_mcp.routing.manual_tracks import TrackSpec
from kicad_mcp.routing.path_planner import RoutePlanningError


def _pair(
    p: tuple[float, float, float, float] = (10.95, 8.5, 19.05, 8.5),
    n: tuple[float, float, float, float] = (10.95, 9.25, 19.05, 9.25),
) -> tuple[TrackSpec, TrackSpec]:
    return (
        TrackSpec(*p, "F_Cu", 0.25, "USB_D_P"),
        TrackSpec(*n, "F_Cu", 0.25, "USB_D_N"),
    )


def test_parallel_usb_pair_has_native_gap_and_zero_skew() -> None:
    from kicad_mcp.routing.differential_pair_candidate import inspect_straight_pair

    result = inspect_straight_pair(*_pair(), gap_mm=0.5, max_skew_mm=0.1)

    assert result["gapMm"] == pytest.approx(0.5)
    assert result["lengthPlusMm"] == pytest.approx(8.1)
    assert result["lengthMinusMm"] == pytest.approx(8.1)
    assert result["skewMm"] == pytest.approx(0.0)


@pytest.mark.parametrize(
    ("p", "n", "reason"),
    [
        ((10.95, 8.5, 19.05, 8.5), (10.95, 9.1, 19.05, 9.1), "gap"),
        ((10.95, 8.5, 19.05, 8.5), (10.95, 9.25, 20.0, 9.25), "length|parallel"),
        ((10.95, 8.5, 19.05, 8.5), (19.05, 9.25, 10.95, 9.25), "direction"),
        ((10.95, 8.5, 19.05, 8.5), (10.95, 9.25, 19.05, 9.65), "parallel"),
        ((10.95, 8.5, 19.05, 8.5), (10.95, 8.5, 19.05, 8.5), "gap"),
    ],
)
def test_rejects_unmatched_pairs(p: tuple[float, ...], n: tuple[float, ...], reason: str) -> None:
    from kicad_mcp.routing.differential_pair_candidate import inspect_straight_pair

    _checked_args = (*_pair(p, n),)
    _checked_kwargs = {"gap_mm": 0.5, "max_skew_mm": 0.1}
    with pytest.raises(RoutePlanningError, match=reason):
        inspect_straight_pair(*_checked_args, **_checked_kwargs)


def test_pair_rejects_different_layer_or_net_pair_names() -> None:
    from kicad_mcp.routing.differential_pair_candidate import inspect_straight_pair

    plus, minus = _pair()
    with pytest.raises(RoutePlanningError, match="layer"):
        inspect_straight_pair(
            plus,
            TrackSpec(10.95, 9.25, 19.05, 9.25, "B_Cu", 0.25, "USB_D_N"),
            gap_mm=0.5,
            max_skew_mm=0.1,
        )

    with pytest.raises(RoutePlanningError, match="net"):
        inspect_straight_pair(
            plus,
            TrackSpec(10.95, 9.25, 19.05, 9.25, "F_Cu", 0.25, "MID"),
            gap_mm=0.5,
            max_skew_mm=0.1,
        )

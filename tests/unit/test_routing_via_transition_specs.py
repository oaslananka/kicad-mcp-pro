"""One through-via transition must not weaken existing single-layer DRC gates."""

from __future__ import annotations

from dataclasses import replace

import pytest

from kicad_mcp.pcb.route_drc_preflight import RoutePreflightError, _validate_specs
from kicad_mcp.routing.manual_tracks import TrackSpec, ViaSpec


def _segments() -> list[TrackSpec]:
    return [
        TrackSpec(10.95, 10, 15, 10, "F_Cu", 0.25, "MID"),
        TrackSpec(15, 10, 19.05, 10, "B_Cu", 0.25, "MID"),
    ]


def _via() -> ViaSpec:
    return ViaSpec(15, 10, 0.8, 0.4, "MID")


def test_one_through_via_allows_a_bounded_f_to_b_transition() -> None:
    _validate_specs(_segments(), through_via=_via())
    with pytest.raises(RoutePreflightError, match="layer"):
        _validate_specs(_segments())


@pytest.mark.parametrize(
    "via",
    [
        ViaSpec(15, 10, 0.3, 0.4, "MID"),
        ViaSpec(15, 10, 0.8, 0.0, "MID"),
        ViaSpec(15, 10, 0.8, 0.4, "GND"),
        ViaSpec(15.2, 10, 0.8, 0.4, "MID"),
        ViaSpec(15, 10, float("nan"), 0.4, "MID"),
    ],
)
def test_invalid_via_geometry_fails_closed(via: ViaSpec) -> None:
    with pytest.raises(RoutePreflightError, match="via|Via|net|endpoint"):
        _validate_specs(_segments(), through_via=via)


def test_via_does_not_allow_two_net_routing_or_unrelated_copper_layer() -> None:
    plus = _segments()
    with pytest.raises(RoutePreflightError, match="net"):
        _validate_specs([plus[0], replace(plus[1], net_name="GND")], through_via=_via())
    with pytest.raises(RoutePreflightError, match="layer"):
        _validate_specs([plus[0], replace(plus[1], layer="In1_Cu")], through_via=_via())
    with pytest.raises(RoutePreflightError, match="via|pair"):
        _validate_specs(
            plus,
            through_via=_via(),
            pair_nets=frozenset(("MID", "GND")),
        )

from __future__ import annotations

from kicad_mcp.tools.pcb import _placement_net_weight, _placement_nets_from_footprints
from kicad_mcp.tools.validation import PlacementAnalysis, _format_placement_score
from kicad_mcp.utils.placement import (
    BGABall,
    ForceDirectedConfig,
    PlacementComponent,
    PlacementNet,
    _centroid,
    _snap,
    force_directed_placement,
    generate_bga_fanout_plan,
)


def test_force_directed_placement_is_deterministic_and_snaps_to_grid() -> None:
    components = [
        PlacementComponent(ref="J1", x=2.0, y=2.0, w=3.0, h=3.0),
        PlacementComponent(ref="U1", x=18.0, y=8.0, w=4.0, h=4.0),
        PlacementComponent(ref="U2", x=32.0, y=18.0, w=4.0, h=4.0),
    ]
    nets = [PlacementNet(name="USB_DP", refs=["J1", "U1", "U2"], weight=1.0)]
    cfg = ForceDirectedConfig(
        iterations=80,
        board_w=40.0,
        board_h=25.0,
        grid_mm=1.0,
        seed=7,
    )

    first = force_directed_placement(components, nets, cfg)
    second = force_directed_placement(components, nets, cfg)

    assert [(item.ref, item.x, item.y) for item in first] == [
        (item.ref, item.x, item.y) for item in second
    ]
    assert all(item.x == round(item.x) for item in first)
    assert all(item.y == round(item.y) for item in first)


def test_force_directed_placement_converges_before_iteration_ceiling() -> None:
    # K7: stopping must be convergence-based (deterministic), never wall-clock,
    # so the same input yields the same board regardless of machine speed.
    components = [
        PlacementComponent(ref="J1", x=2.0, y=2.0, w=3.0, h=3.0),
        PlacementComponent(ref="U1", x=18.0, y=8.0, w=4.0, h=4.0),
        PlacementComponent(ref="U2", x=32.0, y=18.0, w=4.0, h=4.0),
        PlacementComponent(ref="C1", x=25.0, y=5.0, w=2.0, h=2.0),
    ]
    nets = [
        PlacementNet(name="USB_DP", refs=["J1", "U1", "U2"], weight=1.0),
        PlacementNet(name="VBUS", refs=["U1", "C1"], weight=2.0),
    ]
    cfg = ForceDirectedConfig(
        iterations=2000,  # generous ceiling — convergence must stop us first
        board_w=40.0,
        board_h=25.0,
        grid_mm=1.0,
        seed=7,
        convergence_patience=4,
    )

    stats: dict[str, object] = {}
    placed = force_directed_placement(components, nets, cfg, stats=stats)

    # Stopped on convergence, strictly before the 2000-iteration ceiling.
    assert stats["converged"] is True
    iterations_run = stats["iterations_run"]
    assert isinstance(iterations_run, int)
    assert iterations_run < cfg.iterations

    # Deterministic: a second run reproduces the layout exactly.
    second = force_directed_placement(components, nets, cfg)
    assert [(c.ref, c.x, c.y) for c in placed] == [(c.ref, c.x, c.y) for c in second]


def test_force_directed_placement_output_independent_of_wall_clock_budget() -> None:
    # A slow and a fast machine must produce the same board: once the layout has
    # converged the wall-clock safety valve never fires, so the result cannot
    # depend on the time budget. This is the core K7 guarantee.
    components = [
        PlacementComponent(ref="J1", x=2.0, y=2.0, w=3.0, h=3.0),
        PlacementComponent(ref="U1", x=18.0, y=8.0, w=4.0, h=4.0),
        PlacementComponent(ref="U2", x=32.0, y=18.0, w=4.0, h=4.0),
    ]
    nets = [PlacementNet(name="USB_DP", refs=["J1", "U1", "U2"], weight=1.0)]

    def run(max_seconds: float) -> list[tuple[str, float, float]]:
        cfg = ForceDirectedConfig(
            iterations=2000,
            board_w=40.0,
            board_h=25.0,
            grid_mm=1.0,
            seed=7,
            max_seconds=max_seconds,
        )
        return [(c.ref, c.x, c.y) for c in force_directed_placement(components, nets, cfg)]

    # Disabled valve (the deterministic default) vs a generous budget that never
    # fires because convergence is reached first — byte-identical output.
    assert run(0.0) == run(600.0)


def test_force_directed_placement_respects_keepout_regions() -> None:
    components = [PlacementComponent(ref="U1", x=15.0, y=10.0, w=4.0, h=4.0)]
    cfg = ForceDirectedConfig(
        iterations=20,
        board_w=30.0,
        board_h=20.0,
        grid_mm=0.5,
        keepout_regions=[(12.0, 8.0, 18.0, 12.0)],
    )

    placed = force_directed_placement(components, [], cfg)[0]

    assert 0.0 <= placed.x - 2.0
    assert placed.x + 2.0 <= 30.0
    assert 0.0 <= placed.y - 2.0
    assert placed.y + 2.0 <= 20.0
    assert (
        placed.x + 2.0 <= 12.0
        or placed.x - 2.0 >= 18.0
        or placed.y + 2.0 <= 8.0
        or placed.y - 2.0 >= 12.0
    )


def test_board_placement_net_weights_prioritize_power_and_differential_pairs() -> None:
    assert _placement_net_weight("GND") == 3.0
    assert _placement_net_weight("+3V3") == 3.0
    assert _placement_net_weight("USB_DP_P") == 5.0
    assert _placement_net_weight("VIN") == 1.0
    assert _placement_net_weight("NC") == 0.0


def test_board_placement_nets_skip_single_footprint_nets() -> None:
    nets = _placement_nets_from_footprints(
        {
            "U1": {"pad_nets": {"1": "+3V3", "2": "USB_DP_P"}},
            "C1": {"pad_nets": {"1": "+3V3"}},
            "J1": {"pad_nets": {"1": "USB_DP_P", "2": "VIN"}},
        }
    )

    assert [(net.name, net.refs, net.weight) for net in nets] == [
        ("+3V3", ["C1", "U1"], 3.0),
        ("USB_DP_P", ["J1", "U1"], 5.0),
    ]


def test_placement_geometry_helpers_and_bga_fanout_strategies() -> None:
    components = [
        PlacementComponent(ref="U1", x=10.0, y=20.0),
        PlacementComponent(ref="U2", x=20.0, y=40.0),
    ]
    center = _centroid(components, ["U1", "U2"])
    missing_center = _centroid(components, ["J404"])
    balls = [
        BGABall(row="A", col=1, net="D0", x_mm=0.0, y_mm=0.0),
        BGABall(row="B", col=2, net="D1", x_mm=0.8, y_mm=0.8),
    ]

    dog_ear = generate_bga_fanout_plan(balls, pitch_mm=0.5, strategy="dog_ear")
    inline = generate_bga_fanout_plan(balls, pitch_mm=0.8, strategy="inline")

    assert center.x == 15.0
    assert center.y == 30.0
    assert missing_center.x == 0.0
    assert _snap(1.26, 0.5) == 1.5
    assert _snap(1.26, 0.0) == 1.26
    assert dog_ear[0]["track_width_mm"] == 0.1
    assert dog_ear[0]["dog_ear_dx"] != 0.0
    assert inline[0]["track_width_mm"] == 0.15
    assert inline[0]["dog_ear_dx"] == 0.0


# ---------------------------------------------------------------------------
# PlacementAnalysis: new fields (issue #278)
# ---------------------------------------------------------------------------


def _make_analysis(**kwargs: object) -> PlacementAnalysis:
    defaults: dict[str, object] = dict(
        footprint_count=4,
        board_width_mm=40.0,
        board_height_mm=30.0,
        board_area_mm2=1200.0,
        footprint_area_mm2=40.0,
        density_pct=3.3,
        score=90,
    )
    defaults.update(kwargs)
    return PlacementAnalysis(**defaults)


def test_placement_analysis_new_fields_defaults() -> None:
    """New P4-T2 fields have sensible zero defaults."""
    analysis = _make_analysis()
    assert analysis.checked_hs_interfaces == 0
    assert analysis.hs_grouping_violations == []
    assert analysis.return_path_warnings == []
    assert analysis.mount_hole_violations == []
    assert analysis.connector_edge_spec_violations == []
    assert analysis.score_before is None


def test_format_placement_score_includes_hs_and_mechanical_counts() -> None:
    """_format_placement_score must emit high-speed and mechanical summary lines."""
    analysis = _make_analysis(
        checked_hs_interfaces=3,
        mount_hole_violations=["U1 too close to hole at (5, 5)"],
        connector_edge_spec_violations=["J1 is 12 mm from bottom edge (limit 5 mm)"],
    )
    text = _format_placement_score(analysis)
    assert "High-speed interfaces checked: 3" in text
    assert "Mount-hole clearance checks: 1" in text
    assert "Connector edge-spec checks: 1" in text


def test_format_placement_score_shows_before_after_delta() -> None:
    """Before/after delta is shown when score_before is set."""
    analysis = _make_analysis(score=85, score_before=70)
    text = _format_placement_score(analysis)
    assert "Score before auto-placement: 70/100" in text
    assert "+15" in text


def test_format_placement_score_negative_delta() -> None:
    """Negative delta is shown without '+' when score degraded."""
    analysis = _make_analysis(score=60, score_before=70)
    text = _format_placement_score(analysis)
    assert "Score before auto-placement: 70/100" in text
    assert "-10" in text


def test_placement_analysis_hs_violations_in_hard_failures() -> None:
    """High-speed grouping violations lower the score like other hard failures."""
    without_hs = _make_analysis(score=100)
    with_hs = _make_analysis(
        score=80,
        hard_failures=["HS grouping violation: USB3 spans 45 mm"],
        hs_grouping_violations=["USB3 spans 45 mm"],
    )
    assert with_hs.score < without_hs.score
    assert len(with_hs.hard_failures) == 1


def test_placement_analysis_return_path_warnings_in_warnings() -> None:
    """Return-path warnings count toward the warning tally."""
    analysis = _make_analysis(
        warnings=["High-speed interface DDR4 (U1, U2) spans 38 mm — consider tighter grouping."],
        return_path_warnings=["DDR4 proximity warning"],
    )
    assert len(analysis.warnings) == 1

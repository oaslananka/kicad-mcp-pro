from __future__ import annotations

from kicad_mcp.models.power_integrity import CopperWeightCheckInput
from kicad_mcp.power_integrity.copper_weight import (
    CopperTrackObservation,
    PowerIntegrityCopperWeightService,
    ipc_current_capacity_a,
    required_width_mm,
)


def test_capacity_helpers_preserve_existing_physics_contract() -> None:
    capacity_a = ipc_current_capacity_a(
        0.5,
        0.035,
        external=True,
        max_temp_rise_c=10.0,
    )
    width_mm = required_width_mm(
        1.0,
        0.035,
        external=True,
        max_temp_rise_c=10.0,
    )

    assert 0.8 <= capacity_a <= 1.6
    assert 0.2 <= width_mm <= 0.7


def test_service_preserves_no_tracks_warning_contract() -> None:
    payload = CopperWeightCheckInput(net_name="VBUS", expected_current_a=2.0)
    report = PowerIntegrityCopperWeightService().analyze(payload, [])

    assert report.verdict == "WARN"
    assert report.text == "No routed tracks were found for net 'VBUS'."
    assert report.failure_mode == "configuration"
    assert report.evidence == [{"net_name": "VBUS", "track_count": 0}]


def test_service_preserves_longest_track_layer_and_min_width_semantics() -> None:
    payload = CopperWeightCheckInput(
        net_name="3V3",
        expected_current_a=0.5,
        max_temp_rise_c=10.0,
    )
    tracks = [
        CopperTrackObservation(
            width_mm=0.5,
            length_mm=10.0,
            copper_thickness_mm=0.035,
            external=True,
        ),
        CopperTrackObservation(
            width_mm=0.25,
            length_mm=50.0,
            copper_thickness_mm=0.07,
            external=False,
        ),
    ]

    report = PowerIntegrityCopperWeightService().analyze(payload, tracks)

    assert "Copper weight check for 3V3" in report.text
    assert "- Routed track count: 2" in report.text
    assert "- Minimum width: 0.250 mm" in report.text
    assert "- Average width: 0.375 mm" in report.text
    assert "- Copper thickness: 0.0700 mm" in report.text
    assert report.evidence[0]["track_count"] == 2
    assert report.evidence[0]["min_width_mm"] == 0.25

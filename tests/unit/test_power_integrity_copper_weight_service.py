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


def test_service_uses_actual_segment_bottleneck_across_layer_properties() -> None:
    payload = CopperWeightCheckInput(
        net_name="3V3",
        expected_current_a=0.5,
        max_temp_rise_c=10.0,
    )
    bottleneck = CopperTrackObservation(
        width_mm=0.2,
        length_mm=10.0,
        copper_thickness_mm=0.035,
        external=False,
    )
    longest_but_stronger = CopperTrackObservation(
        width_mm=1.0,
        length_mm=50.0,
        copper_thickness_mm=0.07,
        external=True,
    )
    tracks = [bottleneck, longest_but_stronger]

    report = PowerIntegrityCopperWeightService().analyze(payload, tracks)

    expected_capacity = ipc_current_capacity_a(
        bottleneck.width_mm,
        bottleneck.copper_thickness_mm,
        external=bottleneck.external,
        max_temp_rise_c=payload.max_temp_rise_c,
    )
    expected_required_width = max(
        required_width_mm(
            payload.expected_current_a,
            track.copper_thickness_mm,
            external=track.external,
            max_temp_rise_c=payload.max_temp_rise_c,
        )
        for track in tracks
    )

    assert "Copper weight check for 3V3" in report.text
    assert "- Routed track count: 2" in report.text
    assert "- Minimum width: 0.200 mm" in report.text
    assert "- Average width: 0.600 mm" in report.text
    assert "- Bottleneck width: 0.200 mm" in report.text
    assert "- Bottleneck copper thickness: 0.0350 mm" in report.text
    assert "- Bottleneck layer class: internal" in report.text
    evidence = report.evidence[0]
    assert evidence["track_count"] == 2
    assert evidence["min_width_mm"] == 0.2
    assert evidence["bottleneck_width_mm"] == 0.2
    assert evidence["bottleneck_copper_thickness_mm"] == 0.035
    assert evidence["bottleneck_external"] is False
    assert evidence["capacity_a"] == expected_capacity
    assert evidence["required_width_mm"] == expected_required_width

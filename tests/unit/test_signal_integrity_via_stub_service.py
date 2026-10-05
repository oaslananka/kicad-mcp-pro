from __future__ import annotations

from kicad_mcp.models.signal_integrity import ViaStubInput
from kicad_mcp.signal_integrity.via_stub import (
    SignalIntegrityViaStubService,
    ViaStubObservation,
)


def test_via_stub_service_reports_no_matching_vias() -> None:
    payload = ViaStubInput(via_positions=[], frequency_ghz=5.0, er=4.0)

    result = SignalIntegrityViaStubService().analyze(
        payload=payload,
        board_thickness_mm=0.0,
        observations=[],
        critical_frequencies_mhz=[],
    )

    assert result == "No vias matched the supplied positions on the active board."


def test_via_stub_service_warns_when_response_limit_omits_vias() -> None:
    payload = ViaStubInput(via_positions=[], frequency_ghz=5.0, er=4.0)
    observation = ViaStubObservation(
        net_name="GND",
        x_mm=5.0,
        y_mm=5.0,
        via_type_name="VT_THROUGH",
        drill_mm=0.3,
        stub_mm=1.6,
    )

    result = SignalIntegrityViaStubService().analyze(
        payload=payload,
        board_thickness_mm=1.6,
        observations=[observation],
        critical_frequencies_mhz=[],
        omitted_observations=2,
    )

    assert "WARNING: response limit omitted 2 additional vias" in result
    assert "those vias were not checked." in result


def test_via_stub_service_preserves_report_and_critical_frequency_note() -> None:
    payload = ViaStubInput(via_positions=[], frequency_ghz=5.0, er=4.0)
    observations = [
        ViaStubObservation(
            net_name="GND",
            x_mm=5.0,
            y_mm=5.0,
            via_type_name="VT_THROUGH",
            drill_mm=0.3,
            stub_mm=1.6,
        )
    ]

    result = SignalIntegrityViaStubService().analyze(
        payload=payload,
        board_thickness_mm=1.6,
        observations=observations,
        critical_frequencies_mhz=[23_420.0],
    )

    assert result.startswith("Via stub analysis at 5.000 GHz:\n")
    assert "- Assumed board thickness: 1.600 mm" in result
    assert "- Effective dielectric constant: 4.000" in result
    assert "GND @ (5.000, 5.000) mm" in result
    assert "type=VT_THROUGH" in result
    assert "drill=0.300 mm" in result
    assert "stub=1.600 mm" in result
    assert "quarter-wave resonance=" in result
    assert "risk=" in result
    assert "CRITICAL resonance near 23420.0 MHz" in result

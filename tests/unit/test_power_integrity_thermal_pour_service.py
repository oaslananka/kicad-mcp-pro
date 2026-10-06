from __future__ import annotations

from kicad_mcp.models.power_integrity import ThermalPourInput
from kicad_mcp.power_integrity.thermal_pour import (
    CopperPourObservation,
    PowerIntegrityThermalPourService,
)


def test_service_preserves_no_pours_warning() -> None:
    payload = ThermalPourInput(net_name="3V3", expected_power_w=2.0)
    report = PowerIntegrityThermalPourService().analyze(payload, [], max_items=20)

    assert report.verdict == "WARN"
    assert report.text == (
        "No copper pours were found for net '3V3'. "
        "Add a pour or plane for thermal spreading before release."
    )
    assert report.failure_mode == "configuration"
    assert report.evidence == [{"net_name": "3V3", "expected_power_w": 2.0, "matching_pours": 0}]


def test_service_preserves_threshold_layer_rendering_and_truncation() -> None:
    payload = ThermalPourInput(net_name="3V3", expected_power_w=2.0)
    pours = [
        CopperPourObservation("TOP", ("BL_F_Cu",)),
        CopperPourObservation("BOTTOM", ("BL_B_Cu",)),
        CopperPourObservation("EXTRA", ()),
    ]

    report = PowerIntegrityThermalPourService().analyze(payload, pours, max_items=2)

    assert report.verdict == "PASS"
    assert "Thermal copper-pour review for 3V3 (PASS):" in report.text
    assert "- Matching pours / planes: 3" in report.text
    assert "- TOP on BL_F_Cu" in report.text
    assert "- BOTTOM on BL_B_Cu" in report.text
    assert "EXTRA" not in report.text
    assert report.remediation == ""


def test_service_preserves_warn_guidance_when_pour_count_is_low() -> None:
    payload = ThermalPourInput(net_name="VBUS", expected_power_w=2.1)
    pours = [
        CopperPourObservation("P1", ("BL_F_Cu",)),
        CopperPourObservation("", ()),
    ]

    report = PowerIntegrityThermalPourService().analyze(payload, pours, max_items=10)

    assert report.verdict == "WARN"
    assert "- (unnamed) on (unknown layers)" in report.text
    assert "- Consider a wider pour, more copper area, and stitched thermal vias." in report.text
    assert report.remediation == (
        "Increase thermal copper area and stitching, then rerun thermal_check_copper_pour()."
    )

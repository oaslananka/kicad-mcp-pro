from __future__ import annotations

import pytest

from kicad_mcp.models.power_integrity import ThermalViaInput
from kicad_mcp.power_integrity.thermal_via import PowerIntegrityThermalViaService


def test_service_preserves_legacy_power_estimate_contract() -> None:
    payload = ThermalViaInput(
        power_w=2.0,
        ambient_c=25.0,
        max_junction_c=125.0,
        theta_ja_deg_c_w=40.0,
        via_diameter_mm=0.3,
        thermal_resistance_target=5.0,
    )

    result = PowerIntegrityThermalViaService().estimate(payload, board_thickness_mm=1.6)

    assert "Thermal via estimate:" in result
    assert "- Power to spread: 2.000 W" in result
    assert "- Board thickness used: 1.600 mm" in result
    assert "- Single-via thermal resistance estimate: 100.00 C/W" in result
    assert "- Required via-network resistance: 5.00 C/W" in result
    assert "- Required via count: 20" in result
    assert "- Target temperature rise at the interface: 10.00 C" in result
    assert "- Method:" in result


def test_service_preserves_package_power_parallel_path_branch() -> None:
    payload = ThermalViaInput(
        package_power_w=4.0,
        ambient_c=25.0,
        max_junction_c=125.0,
        theta_ja_deg_c_w=40.0,
        via_diameter_mm=0.3,
        thermal_resistance_target=5.0,
    )

    result = PowerIntegrityThermalViaService().estimate(payload, board_thickness_mm=0.8)

    assert "- Power to spread: 4.000 W" in result
    assert "- Board thickness used: 0.800 mm" in result
    assert "- Single-via thermal resistance estimate: 50.00 C/W" in result
    assert "- Required via-network resistance: 66.67 C/W" in result
    assert "- Required via count: 1" in result


def test_service_preserves_missing_power_and_invalid_temperature_errors() -> None:
    service = PowerIntegrityThermalViaService()

    with pytest.raises(ValueError, match="Thermal via power is missing"):
        service.estimate(ThermalViaInput(), board_thickness_mm=1.6)

    with pytest.raises(ValueError, match="max_junction_c must be greater than ambient_c"):
        service.estimate(
            ThermalViaInput(power_w=1.0, ambient_c=125.0, max_junction_c=125.0),
            board_thickness_mm=1.6,
        )

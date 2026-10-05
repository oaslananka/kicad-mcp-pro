from __future__ import annotations

import pytest
from pydantic import ValidationError

from kicad_mcp.power_integrity.voltage_drop import (
    PowerIntegrityVoltageDropService,
    track_resistance_ohm,
)


def test_track_resistance_and_drop_are_reasonable() -> None:
    resistance_ohm = track_resistance_ohm(0.5, 100.0, 1.0)

    assert 0.09 <= resistance_ohm <= 0.11


def test_track_resistance_applies_temperature_coefficient_below_20c() -> None:
    resistance_20c = track_resistance_ohm(0.5, 100.0, 1.0, ambient_temp_c=20.0)
    resistance_0c = track_resistance_ohm(0.5, 100.0, 1.0, ambient_temp_c=0.0)

    assert resistance_0c < resistance_20c
    assert resistance_0c == pytest.approx(
        resistance_20c * (1.0 - (0.0039 * 20.0)),
    )


def test_voltage_drop_service_preserves_response_contract() -> None:
    result = PowerIntegrityVoltageDropService().calculate_voltage_drop(
        current_a=1.0,
        trace_width_mm=0.5,
        trace_length_mm=100.0,
        copper_oz=1.0,
        max_temp_rise_c=10.0,
        internal_layer=False,
    )

    assert result.startswith("PDN voltage-drop estimate:\n")
    assert "- Current: 1.000 A" in result
    assert "- Trace width: 0.500 mm" in result
    assert "- Trace length: 100.000 mm" in result
    assert "- Copper: 1.00 oz (external layer)" in result
    assert "- Estimated resistance:" in result
    assert "- Estimated voltage drop:" in result
    assert "- Estimated current density:" in result
    assert "- IPC-2221 temperature rise:" in result
    assert "- Method:" in result
    assert "Solver verdict:" in result


def test_voltage_drop_service_preserves_internal_layer_label_and_verdict() -> None:
    result = PowerIntegrityVoltageDropService().calculate_voltage_drop(
        current_a=5.0,
        trace_width_mm=0.5,
        trace_length_mm=50.0,
        internal_layer=True,
    )

    assert "(internal layer)" in result
    assert "(FAIL;" in result


def test_voltage_drop_service_keeps_pydantic_input_validation() -> None:
    service = PowerIntegrityVoltageDropService()

    with pytest.raises(ValidationError):
        service.calculate_voltage_drop(
            current_a=1.0,
            trace_width_mm=0.0,
            trace_length_mm=100.0,
        )

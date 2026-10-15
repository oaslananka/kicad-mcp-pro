from __future__ import annotations

import pytest
from pydantic import ValidationError

from kicad_mcp.signal_integrity.impedance import SignalIntegrityImpedanceService


def test_calculate_trace_impedance_preserves_response_contract() -> None:
    service = SignalIntegrityImpedanceService()

    result = service.calculate_trace_impedance(
        width_mm=0.34,
        height_mm=0.18,
        er=4.2,
        trace_type="microstrip",
        copper_oz=1.0,
        spacing_mm=0.2,
    )

    assert result.startswith("Trace impedance estimate:\n")
    assert "- Width: 0.3400 mm" in result
    assert "- Estimated single-ended impedance:" in result
    assert "- Estimated differential impedance:" in result
    assert "Solver verdict:" in result
    assert "release_signoff=blocked" in result


def test_width_synthesis_preserves_response_contract() -> None:
    service = SignalIntegrityImpedanceService()

    result = service.calculate_trace_width_for_impedance(
        target_ohm=50.0,
        height_mm=0.18,
        er=4.2,
        trace_type="microstrip",
        copper_oz=1.0,
        spacing_mm=0.2,
    )

    assert result.startswith("Width synthesis for 50.00 ohm:\n")
    assert "- Estimated single-ended impedance:" in result
    assert "- Gap / spacing: 0.2000 mm" in result
    assert "Solver verdict:" in result


@pytest.mark.parametrize(
    ("method", "kwargs"),
    [
        (
            "calculate_trace_impedance",
            {"width_mm": 0.0, "height_mm": 0.18},
        ),
        (
            "calculate_trace_width_for_impedance",
            {"target_ohm": 0.5, "height_mm": 0.18},
        ),
    ],
)
def test_input_validation_remains_pydantic(method: str, kwargs: dict[str, float]) -> None:
    service = SignalIntegrityImpedanceService()
    fn = getattr(service, method)

    with pytest.raises(ValidationError):
        fn(**kwargs)

from __future__ import annotations

from types import SimpleNamespace

from kicad_mcp.models.power_integrity import ThermalPlaneSpreadInput
from kicad_mcp.power_integrity import thermal_plane_spreading as module


def _payload(**overrides: float) -> ThermalPlaneSpreadInput:
    data = {
        "power_w": 1.5,
        "plane_width_mm": 40.0,
        "plane_height_mm": 30.0,
        "source_width_mm": 50.0,
        "source_height_mm": 35.0,
        "copper_oz": 1.0,
        "ambient_c": 25.0,
        "film_coefficient_w_per_m2_k": 20.0,
        "max_temp_rise_c": 40.0,
    }
    data.update(overrides)
    return ThermalPlaneSpreadInput(**data)


def test_service_preserves_solver_spec_and_verdict_rendering(monkeypatch) -> None:
    captured: list[object] = []

    def solve(spec):
        captured.append(spec)
        return SimpleNamespace(
            peak_temp_c=55.0,
            peak_rise_c=30.0,
            average_rise_c=12.0,
            grid_rows=16,
            grid_cols=20,
            iterations=42,
            converged=True,
            spreading_length_mm=7.5,
        )

    monkeypatch.setattr(module, "solve_plane_temperature", solve)
    result = module.PowerIntegrityThermalPlaneService().analyze(_payload())

    assert len(captured) == 1
    spec = captured[0]
    assert spec.power_w == 1.5
    assert spec.plane_width_mm == 40.0
    assert spec.plane_height_mm == 30.0
    assert spec.source_width_mm == 40.0
    assert spec.source_height_mm == 30.0
    assert spec.copper_weight_oz == 1.0
    assert spec.ambient_c == 25.0
    assert spec.film_coefficient_w_per_m2_k == 20.0

    assert result.verdict == "PASS"
    assert "Thermal plane-spreading analysis:" in result.text
    assert "- Grid: 16 x 20 (converged in 42 iters)" in result.text
    assert "- Peak temperature rise: 30.0 C (PASS;" in result.text
    assert "- Average temperature rise: 12.0 C" in result.text
    assert "- Peak junction temperature: 55.0 C (ambient 25.0 C)" in result.text
    assert "- Method: 2-D finite-difference copper-plane spreading solve" in result.text
    assert result.evidence[0]["converged"] is True
    assert result.evidence[0]["iterations"] == 42


def test_service_preserves_fail_remediation(monkeypatch) -> None:
    monkeypatch.setattr(
        module,
        "solve_plane_temperature",
        lambda spec: SimpleNamespace(
            peak_temp_c=115.0,
            peak_rise_c=90.0,
            average_rise_c=40.0,
            grid_rows=12,
            grid_cols=12,
            iterations=100,
            converged=False,
            spreading_length_mm=5.0,
        ),
    )

    result = module.PowerIntegrityThermalPlaneService().analyze(_payload())

    assert result.verdict == "FAIL"
    assert "iteration-capped" in result.text
    assert result.remediation == (
        "Increase copper area, reduce power density, or add thermal vias, then "
        "rerun thermal_simulate_plane_spreading()."
    )

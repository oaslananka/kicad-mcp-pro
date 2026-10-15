"""2-D finite-difference thermal spreading solver physics (work order P3-T4)."""

from __future__ import annotations

import pytest

from kicad_mcp.utils.solver_seams import THERMAL_FD_METHOD, thermal_fd_method
from kicad_mcp.utils.thermal_solver import (
    ThermalPlaneSpec,
    solve_plane_temperature,
)


def _spec(**overrides: float) -> ThermalPlaneSpec:
    base: dict[str, float] = dict(power_w=2.0, plane_width_mm=40.0, plane_height_mm=40.0)
    base.update(overrides)
    return ThermalPlaneSpec(**base)  # type: ignore[arg-type]


def test_solver_conserves_energy() -> None:
    """At steady state all injected power leaves through the convective sink."""
    spec = _spec()
    result = solve_plane_temperature(spec)
    assert result.converged
    area_m2 = (spec.plane_width_mm / 1000.0) * (spec.plane_height_mm / 1000.0)
    dissipated_w = result.average_rise_c * spec.film_coefficient_w_per_m2_k * area_m2
    assert dissipated_w == pytest.approx(spec.power_w, rel=1e-2)


def test_peak_exceeds_average_and_source_is_hottest() -> None:
    result = solve_plane_temperature(_spec())
    assert result.peak_rise_c > result.average_rise_c > 0.0
    assert result.peak_temp_c == pytest.approx(result.ambient_c + result.peak_rise_c)


def test_larger_plane_and_more_cooling_lower_the_peak() -> None:
    base = solve_plane_temperature(_spec()).peak_rise_c
    bigger = solve_plane_temperature(_spec(plane_width_mm=80.0, plane_height_mm=80.0)).peak_rise_c
    cooler = solve_plane_temperature(_spec(film_coefficient_w_per_m2_k=80.0)).peak_rise_c
    assert bigger < base
    assert cooler < base


def test_thicker_copper_spreads_more_and_lowers_the_peak() -> None:
    thin = solve_plane_temperature(_spec(copper_weight_oz=1.0)).peak_rise_c
    thick = solve_plane_temperature(_spec(copper_weight_oz=4.0)).peak_rise_c
    assert thick < thin


def test_zero_power_is_isothermal_at_ambient() -> None:
    result = solve_plane_temperature(_spec(power_w=0.0))
    assert result.peak_rise_c == 0.0
    assert result.peak_temp_c == pytest.approx(result.ambient_c)


def test_invalid_specs_raise() -> None:
    invalid_plane_spec = _spec(plane_width_mm=-1.0)
    with pytest.raises(ValueError):
        solve_plane_temperature(invalid_plane_spec)

    # Source larger than the plane is non-physical.
    invalid_source_spec = _spec(source_width_mm=100.0)
    with pytest.raises(ValueError):
        solve_plane_temperature(invalid_source_spec)

    invalid_film_spec = _spec(film_coefficient_w_per_m2_k=0.0)
    with pytest.raises(ValueError):
        solve_plane_temperature(invalid_film_spec)


def test_thermal_fd_method_is_solver_grade_but_not_fea() -> None:
    method = thermal_fd_method()
    assert method["solver_grade"] is True
    assert method["verdict"] == "solver-grade"
    assert method["release_signoff"] == "eligible"
    assert method["critic_only"] is False
    assert method["method"] == THERMAL_FD_METHOD
    assert "not a" in method["accuracy"].lower()

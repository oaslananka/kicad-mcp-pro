"""FastMCP-independent copper-plane thermal spreading analysis."""

from __future__ import annotations

from dataclasses import dataclass

from ..models.power_integrity import ThermalPlaneSpreadInput
from ..models.verdict import VerdictReport
from ..utils.solver_seams import format_solver_verdict, thermal_fd_method
from ..utils.thermal_solver import ThermalPlaneSpec, solve_plane_temperature
from ..verdicts import three_level_verdict, warn_max_from


@dataclass(frozen=True)
class PowerIntegrityThermalPlaneService:
    """Own deterministic copper-plane thermal spreading analysis."""

    def analyze(self, payload: ThermalPlaneSpreadInput) -> VerdictReport:
        spec = ThermalPlaneSpec(
            power_w=payload.power_w,
            plane_width_mm=payload.plane_width_mm,
            plane_height_mm=payload.plane_height_mm,
            source_width_mm=min(payload.source_width_mm, payload.plane_width_mm),
            source_height_mm=min(payload.source_height_mm, payload.plane_height_mm),
            copper_weight_oz=payload.copper_oz,
            ambient_c=payload.ambient_c,
            film_coefficient_w_per_m2_k=payload.film_coefficient_w_per_m2_k,
        )
        result = solve_plane_temperature(spec)
        fail_rise_c = warn_max_from(payload.max_temp_rise_c)
        verdict = three_level_verdict(
            result.peak_rise_c,
            pass_max=payload.max_temp_rise_c,
            warn_max=fail_rise_c,
        )
        lines = [
            "Thermal plane-spreading analysis:",
            f"- Source power: {payload.power_w:.3f} W",
            f"- Copper plane: {payload.plane_width_mm:.1f} x {payload.plane_height_mm:.1f} mm "
            f"@ {payload.copper_oz:.2f} oz",
            f"- Grid: {result.grid_rows} x {result.grid_cols} "
            f"({'converged' if result.converged else 'iteration-capped'} "
            f"in {result.iterations} iters)",
            f"- Lateral spreading length: {result.spreading_length_mm:.1f} mm",
            f"- Peak temperature rise: {result.peak_rise_c:.1f} C "
            f"({verdict}; PASS <= {payload.max_temp_rise_c:.1f} C, "
            f"WARN <= {fail_rise_c:.1f} C, FAIL > {fail_rise_c:.1f} C)",
            f"- Average temperature rise: {result.average_rise_c:.1f} C",
            f"- Peak junction temperature: {result.peak_temp_c:.1f} C "
            f"(ambient {payload.ambient_c:.1f} C)",
        ]
        method = thermal_fd_method()
        lines.append(f"- Method: {method['method']} — {method['accuracy']}")
        lines.append(f"- {format_solver_verdict(method)}")
        return VerdictReport.from_text_verdict(
            text="\n".join(lines),
            summary=(
                f"Peak temperature rise is {result.peak_rise_c:.1f} C against "
                f"{payload.max_temp_rise_c:.1f} C limit."
            ),
            verdict=verdict,
            source="thermal_simulate_plane_spreading",
            evidence=[
                {
                    "power_w": payload.power_w,
                    "peak_rise_c": result.peak_rise_c,
                    "average_rise_c": result.average_rise_c,
                    "max_temp_rise_c": payload.max_temp_rise_c,
                    "converged": result.converged,
                    "iterations": result.iterations,
                }
            ],
            remediation=(
                "Increase copper area, reduce power density, or add thermal vias, then "
                "rerun thermal_simulate_plane_spreading()."
            )
            if verdict != "PASS"
            else "",
            metadata={"domain": "thermal", "solver": method["method"]},
        )

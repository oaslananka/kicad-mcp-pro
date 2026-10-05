"""FastMCP-independent PDN voltage-drop estimation."""

from __future__ import annotations

from dataclasses import dataclass

from ..models.power_integrity import VoltageDropInput
from ..utils.impedance import copper_thickness_mm
from ..utils.pdn_mesh import ipc2221_temperature_rise_c
from ..utils.solver_seams import format_solver_verdict, ir_drop_method
from ..verdicts import three_level_verdict, warn_max_from

_COPPER_RESISTIVITY_OHM_M = 1.724e-8
_TEMPERATURE_COEFFICIENT = 0.0039


def track_resistance_ohm(
    trace_width_mm: float,
    trace_length_mm: float,
    copper_oz: float,
    ambient_temp_c: float = 25.0,
) -> float:
    """Estimate trace resistance from geometry, copper weight, and temperature."""
    thickness_m = copper_thickness_mm(copper_oz) / 1_000.0
    width_m = trace_width_mm / 1_000.0
    length_m = trace_length_mm / 1_000.0
    area_m2 = width_m * thickness_m
    base_resistance = _COPPER_RESISTIVITY_OHM_M * length_m / area_m2
    return base_resistance * (1.0 + (_TEMPERATURE_COEFFICIENT * (ambient_temp_c - 20.0)))


@dataclass(frozen=True)
class PowerIntegrityVoltageDropService:
    """Own deterministic single-trace PDN voltage-drop estimation."""

    def calculate_voltage_drop(
        self,
        current_a: float,
        trace_width_mm: float,
        trace_length_mm: float,
        copper_oz: float = 1.0,
        max_temp_rise_c: float = 10.0,
        internal_layer: bool = False,
    ) -> str:
        payload = VoltageDropInput(
            current_a=current_a,
            trace_width_mm=trace_width_mm,
            trace_length_mm=trace_length_mm,
            copper_oz=copper_oz,
        )
        resistance_ohm = track_resistance_ohm(
            payload.trace_width_mm,
            payload.trace_length_mm,
            payload.copper_oz,
        )
        drop_v = payload.current_a * resistance_ohm
        current_density_a_per_mm2 = payload.current_a / (
            payload.trace_width_mm * copper_thickness_mm(payload.copper_oz)
        )
        temp_rise_c = ipc2221_temperature_rise_c(
            payload.current_a,
            payload.trace_width_mm,
            payload.copper_oz,
            internal=internal_layer,
        )
        fail_temp_c = warn_max_from(max_temp_rise_c)
        fusing_verdict = three_level_verdict(
            temp_rise_c,
            pass_max=max_temp_rise_c,
            warn_max=fail_temp_c,
        )
        lines = [
            "PDN voltage-drop estimate:",
            f"- Current: {payload.current_a:.3f} A",
            f"- Trace width: {payload.trace_width_mm:.3f} mm",
            f"- Trace length: {payload.trace_length_mm:.3f} mm",
            f"- Copper: {payload.copper_oz:.2f} oz "
            f"({'internal' if internal_layer else 'external'} layer)",
            f"- Estimated resistance: {resistance_ohm:.5f} ohm",
            f"- Estimated voltage drop: {drop_v * 1_000.0:.2f} mV",
            f"- Estimated current density: {current_density_a_per_mm2:.2f} A/mm^2",
            f"- IPC-2221 temperature rise: {temp_rise_c:.1f} C ({fusing_verdict}; "
            f"PASS <= {max_temp_rise_c:.1f} C, WARN <= {fail_temp_c:.1f} C, "
            f"FAIL > {fail_temp_c:.1f} C)",
        ]
        method = ir_drop_method()
        lines.append(f"- Method: {method['method']} — {method['accuracy']}")
        lines.append(f"- {format_solver_verdict(method)}")
        if not method["solver_grade"]:
            lines.append(f"- Note: {method['note']}")
        return "\n".join(lines)

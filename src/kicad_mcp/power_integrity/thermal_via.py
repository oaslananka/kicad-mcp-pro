"""FastMCP-independent thermal-via estimation."""

from __future__ import annotations

import math
from dataclasses import dataclass

from ..models.power_integrity import ThermalViaInput
from ..utils.solver_seams import format_solver_verdict, thermal_method

DEFAULT_BOARD_THICKNESS_MM = 1.6


@dataclass(frozen=True)
class PowerIntegrityThermalViaService:
    """Own deterministic thermal-via estimation and rendering."""

    def estimate(self, payload: ThermalViaInput, *, board_thickness_mm: float) -> str:
        effective_power_w = payload.package_power_w or payload.power_w
        if effective_power_w is None:
            raise ValueError(
                "Thermal via power is missing. Provide either 'package_power_w' for the "
                "package thermal-envelope workflow or legacy 'power_w'."
            )
        if payload.max_junction_c <= payload.ambient_c:
            raise ValueError("max_junction_c must be greater than ambient_c.")

        allowed_total_theta = (payload.max_junction_c - payload.ambient_c) / effective_power_w
        if payload.package_power_w is not None and payload.theta_ja_deg_c_w > allowed_total_theta:
            required_via_network_theta = 1.0 / (
                (1.0 / allowed_total_theta) - (1.0 / payload.theta_ja_deg_c_w)
            )
        else:
            required_via_network_theta = min(
                payload.thermal_resistance_target,
                allowed_total_theta,
            )

        single_via_theta = (
            100.0
            * (0.3 / payload.via_diameter_mm)
            * (board_thickness_mm / DEFAULT_BOARD_THICKNESS_MM)
        )
        via_count = max(1, math.ceil(single_via_theta / required_via_network_theta))
        delta_temp_c = effective_power_w * required_via_network_theta

        lines = [
            "Thermal via estimate:",
            f"- Power to spread: {effective_power_w:.3f} W",
            (
                f"- Ambient / max junction: {payload.ambient_c:.1f} C / "
                f"{payload.max_junction_c:.1f} C"
            ),
            f"- Package theta JA: {payload.theta_ja_deg_c_w:.2f} C/W",
            f"- Via diameter: {payload.via_diameter_mm:.3f} mm",
            f"- Board thickness used: {board_thickness_mm:.3f} mm",
            "- Single-via rule of thumb: 0.3 mm, 1 oz copper is approximately 100 C/W",
            f"- Single-via thermal resistance estimate: {single_via_theta:.2f} C/W",
            f"- Required via-network resistance: {required_via_network_theta:.2f} C/W",
            f"- Required via count: {via_count}",
            f"- Target temperature rise at the interface: {delta_temp_c:.2f} C",
        ]
        method = thermal_method()
        lines.append(f"- Method: {method['method']} — {method['accuracy']}")
        lines.append(f"- {format_solver_verdict(method)}")
        if not method["solver_grade"]:
            lines.append(f"- Note: {method['note']}")
        return "\n".join(lines)

"""Lightweight DC PDN mesh solver for file-based power integrity checks."""

from __future__ import annotations

import math
from dataclasses import dataclass, field

COPPER_RESISTIVITY_OHM_M = 1.724e-8
OZ_TO_THICKNESS_MM = 0.0348
_MM_TO_MILS = 1.0 / 0.0254
# IPC-2221 conductor temperature-rise constants: I = k * dT^0.44 * A_mils2^0.725.
_IPC2221_K_EXTERNAL = 0.048
_IPC2221_K_INTERNAL = 0.024


def ipc2221_temperature_rise_c(
    current_a: float,
    width_mm: float,
    copper_weight_oz: float = 1.0,
    *,
    internal: bool = False,
) -> float:
    """Return the IPC-2221 conductor temperature rise (degrees C) for a DC current.

    Inverts the IPC-2221 ampacity curve ``I = k * dT^0.44 * A^0.725`` (A is the copper
    cross-section in mils^2; k is 0.048 for external layers, 0.024 for internal) to solve
    for ``dT`` given the current. This is the standard closed-form trace-fusing /
    self-heating estimate, named to its source.
    """
    if width_mm <= 0 or copper_weight_oz <= 0:
        raise ValueError("width_mm and copper_weight_oz must be positive.")
    if current_a <= 0:
        return 0.0
    width_mils = width_mm * _MM_TO_MILS
    thickness_mils = copper_weight_oz * OZ_TO_THICKNESS_MM * _MM_TO_MILS
    area_mils2 = width_mils * thickness_mils
    k = _IPC2221_K_INTERNAL if internal else _IPC2221_K_EXTERNAL
    # Inverted formula: temperature rise dT from current and area
    return float((current_a / (k * area_mils2**0.725)) ** (1.0 / 0.44))


@dataclass(frozen=True)
class PdnLoad:
    """A load attached to a power net."""

    ref: str
    current_a: float
    distance_mm: float


@dataclass(frozen=True)
class PdnDecouplingCap:
    """A decoupling capacitor model used for AC PDN impedance estimates."""

    ref: str
    capacitance_f: float
    esr_ohm: float = 0.02
    esl_h: float = 1e-9


@dataclass(frozen=True)
class PdnResult:
    """PDN voltage-drop result."""

    max_drop_mv: float
    drops_mv: dict[str, float] = field(default_factory=dict)
    violations: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)
    impedance_ohm: dict[float, float] = field(default_factory=dict)
    max_impedance_ohm: float = 0.0
    impedance_violations: list[str] = field(default_factory=list)


class PdnMesh:
    """Simple resistive PDN model using copper trace resistance."""

    def solve(
        self,
        *,
        net_name: str,
        source_ref: str,
        loads: list[PdnLoad],
        trace_width_mm: float,
        copper_weight_oz: float = 1.0,
        nominal_voltage_v: float = 3.3,
        tolerance_pct: float = 5.0,
        frequency_points_hz: list[float] | None = None,
        decoupling_caps: list[PdnDecouplingCap] | None = None,
        target_impedance_ohm: float | None = None,
    ) -> PdnResult:
        """Estimate voltage drop for each load using a 1-D equivalent resistance."""
        if trace_width_mm <= 0:
            raise ValueError("trace_width_mm must be positive.")
        if copper_weight_oz <= 0:
            raise ValueError("copper_weight_oz must be positive.")
        thickness_mm = copper_weight_oz * OZ_TO_THICKNESS_MM
        area_m2 = (trace_width_mm / 1000.0) * (thickness_mm / 1000.0)
        limit_mv = nominal_voltage_v * (tolerance_pct / 100.0) * 1000.0
        drops: dict[str, float] = {}
        violations: list[str] = []
        recommendations: list[str] = []
        worst_resistance_ohm = 0.0
        for load in loads:
            resistance_ohm = COPPER_RESISTIVITY_OHM_M * (load.distance_mm / 1000.0) / area_m2
            worst_resistance_ohm = max(worst_resistance_ohm, resistance_ohm)
            drop_mv = load.current_a * resistance_ohm * 1000.0
            drops[load.ref] = drop_mv
            if drop_mv > limit_mv:
                violations.append(
                    f"{load.ref} drops {drop_mv:.1f} mV on {net_name}, above {limit_mv:.1f} mV."
                )
        if violations:
            recommendations.append(
                f"Widen {net_name} traces from {trace_width_mm:.2f} mm or add copper pours "
                f"between {source_ref} and the listed loads."
            )
        impedance_ohm = _solve_ac_impedance(
            rail_resistance_ohm=worst_resistance_ohm,
            decoupling_caps=decoupling_caps or [],
            frequency_points_hz=frequency_points_hz or [],
        )
        impedance_violations: list[str] = []
        if target_impedance_ohm is not None:
            for frequency_hz, impedance in impedance_ohm.items():
                if impedance > target_impedance_ohm:
                    impedance_violations.append(
                        f"{net_name} impedance is {impedance:.4f} ohm at "
                        f"{frequency_hz:.0f} Hz, above {target_impedance_ohm:.4f} ohm."
                    )
        if impedance_violations:
            recommendations.append(
                f"Add lower-ESL decoupling or more plane capacitance on {net_name} "
                "to reduce high-frequency PDN impedance."
            )
        return PdnResult(
            max_drop_mv=max(drops.values(), default=0.0),
            drops_mv=drops,
            violations=violations,
            recommendations=recommendations,
            impedance_ohm=impedance_ohm,
            max_impedance_ohm=max(impedance_ohm.values(), default=0.0),
            impedance_violations=impedance_violations,
        )


def _solve_ac_impedance(
    *,
    rail_resistance_ohm: float,
    decoupling_caps: list[PdnDecouplingCap],
    frequency_points_hz: list[float],
) -> dict[float, float]:
    points: dict[float, float] = {}
    if not frequency_points_hz:
        return points
    for frequency_hz in frequency_points_hz:
        if frequency_hz <= 0:
            continue
        branch_impedances = [complex(max(rail_resistance_ohm, 1e-9), 0.0)]
        omega = 2.0 * math.pi * frequency_hz
        for cap in decoupling_caps:
            if cap.capacitance_f <= 0:
                continue
            capacitive_reactance = -1.0 / (omega * cap.capacitance_f)
            inductive_reactance = omega * max(cap.esl_h, 0.0)
            branch_impedances.append(
                complex(max(cap.esr_ohm, 1e-9), inductive_reactance + capacitive_reactance)
            )
        admittance = sum(1.0 / impedance for impedance in branch_impedances)
        if admittance:
            points[float(frequency_hz)] = abs(1.0 / admittance)
    return points

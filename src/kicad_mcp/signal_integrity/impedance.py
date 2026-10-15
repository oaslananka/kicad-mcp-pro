"""FastMCP-independent signal-integrity impedance calculations."""

from __future__ import annotations

from dataclasses import dataclass

from ..models.signal_integrity import TraceImpedanceInput, TraceWidthForImpedanceInput
from ..utils.field_solver import impedance_method
from ..utils.impedance import (
    copper_thickness_mm,
    differential_impedance,
    solve_width_for_impedance,
    trace_impedance,
)
from ..utils.solver_seams import format_solver_verdict


def format_impedance_result(
    *,
    title: str,
    trace_type: str,
    width_mm: float,
    height_mm: float,
    er: float,
    copper_oz: float,
    impedance_ohm: float,
    effective_er: float,
    spacing_mm: float | None = None,
    differential_ohm: float | None = None,
) -> str:
    """Render the stable impedance response used by both public tools."""
    lines = [
        title,
        f"- Trace type: {trace_type}",
        f"- Width: {width_mm:.4f} mm",
        f"- Dielectric height: {height_mm:.4f} mm",
        f"- Copper: {copper_oz:.2f} oz ({copper_thickness_mm(copper_oz):.4f} mm)",
        f"- Relative permittivity (Er): {er:.3f}",
        f"- Effective permittivity: {effective_er:.3f}",
        f"- Estimated single-ended impedance: {impedance_ohm:.2f} ohm",
    ]
    if spacing_mm is not None:
        lines.append(f"- Gap / spacing: {spacing_mm:.4f} mm")
    if differential_ohm is not None:
        lines.append(f"- Estimated differential impedance: {differential_ohm:.2f} ohm")
    method = impedance_method()
    lines.append(f"- Method: {method['method']} — {method['accuracy']}")
    lines.append(f"- {format_solver_verdict(method)}")
    note = method.get("note")
    if note:
        lines.append(f"- Note: {note}")
    return "\n".join(lines)


@dataclass(frozen=True)
class SignalIntegrityImpedanceService:
    """Own trace-impedance estimation and width synthesis behavior."""

    def calculate_trace_impedance(
        self,
        width_mm: float,
        height_mm: float,
        er: float = 4.2,
        trace_type: str = "microstrip",
        copper_oz: float = 1.0,
        spacing_mm: float = 0.2,
    ) -> str:
        payload = TraceImpedanceInput(
            width_mm=width_mm,
            height_mm=height_mm,
            er=er,
            trace_type=trace_type,
            copper_oz=copper_oz,
            spacing_mm=spacing_mm,
        )
        impedance_ohm, effective_er = trace_impedance(
            payload.width_mm,
            payload.height_mm,
            payload.er,
            trace_type=payload.trace_type,
            copper_oz=payload.copper_oz,
            spacing_mm=payload.spacing_mm,
        )
        differential_ohm, _ = differential_impedance(
            payload.width_mm,
            payload.height_mm,
            payload.spacing_mm,
            payload.er,
            trace_type=payload.trace_type,
            copper_oz=payload.copper_oz,
        )
        return format_impedance_result(
            title="Trace impedance estimate:",
            trace_type=payload.trace_type,
            width_mm=payload.width_mm,
            height_mm=payload.height_mm,
            er=payload.er,
            copper_oz=payload.copper_oz,
            impedance_ohm=impedance_ohm,
            effective_er=effective_er,
            spacing_mm=payload.spacing_mm,
            differential_ohm=differential_ohm,
        )

    def calculate_trace_width_for_impedance(
        self,
        target_ohm: float,
        height_mm: float,
        er: float = 4.2,
        trace_type: str = "microstrip",
        copper_oz: float = 1.0,
        spacing_mm: float = 0.2,
    ) -> str:
        payload = TraceWidthForImpedanceInput(
            target_ohm=target_ohm,
            height_mm=height_mm,
            er=er,
            trace_type=trace_type,
            copper_oz=copper_oz,
            spacing_mm=spacing_mm,
        )
        solved_width_mm = solve_width_for_impedance(
            payload.target_ohm,
            payload.height_mm,
            payload.er,
            trace_type=payload.trace_type,
            copper_oz=payload.copper_oz,
            spacing_mm=payload.spacing_mm,
        )
        impedance_ohm, effective_er = trace_impedance(
            solved_width_mm,
            payload.height_mm,
            payload.er,
            trace_type=payload.trace_type,
            copper_oz=payload.copper_oz,
            spacing_mm=payload.spacing_mm,
        )
        return format_impedance_result(
            title=f"Width synthesis for {payload.target_ohm:.2f} ohm:",
            trace_type=payload.trace_type,
            width_mm=solved_width_mm,
            height_mm=payload.height_mm,
            er=payload.er,
            copper_oz=payload.copper_oz,
            impedance_ohm=impedance_ohm,
            effective_er=effective_er,
            spacing_mm=payload.spacing_mm,
        )

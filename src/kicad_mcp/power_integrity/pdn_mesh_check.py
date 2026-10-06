"""FastMCP-independent PDN mesh analysis."""

from __future__ import annotations

from dataclasses import dataclass

from ..models.verdict import Verdict, VerdictReport
from ..utils.pdn_mesh import PdnDecouplingCap, PdnLoad, PdnMesh
from ..utils.solver_seams import format_solver_verdict, pdn_mesh_method


@dataclass(frozen=True)
class PowerIntegrityPdnMeshService:
    """Own deterministic PDN mesh analysis and result rendering."""

    def analyze(
        self,
        *,
        net_name: str,
        source_ref: str,
        load_refs: list[str],
        trace_width_mm: float,
        load_current_a: float = 0.1,
        trace_length_mm: float = 100.0,
        copper_weight_oz: float = 1.0,
        nominal_voltage_v: float = 3.3,
        frequency_points_hz: list[float] | None = None,
        decoupling_caps_uf: list[float] | None = None,
        target_impedance_ohm: float | None = None,
        decoupling_esr_mohm: float = 20.0,
        decoupling_esl_nh: float = 1.0,
    ) -> VerdictReport:
        loads = [
            PdnLoad(
                ref=reference,
                current_a=load_current_a,
                distance_mm=trace_length_mm * ((index + 1) / max(1, len(load_refs))),
            )
            for index, reference in enumerate(load_refs)
        ]
        result = PdnMesh().solve(
            net_name=net_name,
            source_ref=source_ref,
            loads=loads,
            trace_width_mm=trace_width_mm,
            copper_weight_oz=copper_weight_oz,
            nominal_voltage_v=nominal_voltage_v,
            frequency_points_hz=frequency_points_hz,
            decoupling_caps=[
                PdnDecouplingCap(
                    ref=f"C{index}",
                    capacitance_f=value_uf * 1e-6,
                    esr_ohm=decoupling_esr_mohm / 1000.0,
                    esl_h=decoupling_esl_nh * 1e-9,
                )
                for index, value_uf in enumerate(decoupling_caps_uf or [], start=1)
            ],
            target_impedance_ohm=target_impedance_ohm,
        )
        lines = [
            "PDN mesh check:",
            f"- Net: {net_name}",
            f"- Source: {source_ref}",
            f"- Max drop: {result.max_drop_mv:.2f} mV",
            f"- Violations: {len(result.violations)}",
        ]
        lines.extend(f"- {ref}: {drop:.2f} mV" for ref, drop in result.drops_mv.items())
        lines.extend(f"- FAIL: {item}" for item in result.violations)
        if result.impedance_ohm:
            lines.append(f"- Max AC impedance: {result.max_impedance_ohm:.4f} ohm")
            for frequency_hz, impedance in result.impedance_ohm.items():
                lines.append(f"- Z({frequency_hz:.0f} Hz): {impedance:.4f} ohm")
        lines.extend(f"- IMPEDANCE FAIL: {item}" for item in result.impedance_violations)
        lines.extend(f"- Recommendation: {item}" for item in result.recommendations)
        mesh_method = pdn_mesh_method()
        lines.append(f"- Method: {mesh_method['method']} — {mesh_method['accuracy']}")
        lines.append(f"- {format_solver_verdict(mesh_method)}")
        verdict: Verdict = "FAIL" if result.violations or result.impedance_violations else "PASS"
        return VerdictReport.from_text_verdict(
            text="\n".join(lines),
            summary=(
                f"PDN mesh check completed for {net_name} with "
                f"{len(result.violations) + len(result.impedance_violations)} violation(s)."
            ),
            verdict=verdict,
            source="check_power_integrity",
            evidence=[
                {
                    "net_name": net_name,
                    "source_ref": source_ref,
                    "load_refs": load_refs,
                    "max_drop_mv": result.max_drop_mv,
                    "violations": result.violations,
                    "impedance_violations": result.impedance_violations,
                }
            ],
            remediation=(
                "Widen copper, shorten paths, add decoupling, then rerun check_power_integrity()."
            )
            if verdict != "PASS"
            else "",
            metadata={"domain": "power_integrity"},
        )

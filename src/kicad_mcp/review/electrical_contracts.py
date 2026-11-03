"""Electrical, power, derating, and thermal review contracts (#1584, T7).

Principles:
1. Connects electrical contracts, component derating, and thermal observations to explicit
   requirements and verified source models.
2. Missing load/environment/operating conditions evaluate to NOT_ASSESSED, never PASS.
3. Recommended operating conditions (ROC) and absolute maximum ratings (AMR) are strictly
   decoupled: operating above ROC yields WARN (reliability derating); operating above AMR
   yields FAIL (electrical overstress defect).
4. Distinguishes typical-only analysis from worst-case analysis. Typical-only calculations
   record explicit metadata and cannot establish worst-case bounds.
5. Operating conditions or geometry outside a solver's physical validity range cannot return PASS.
6. High-voltage, battery, fault, and FMEA areas retain explicit specialist review and
   physical measurement contracts.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..models.power_integrity import VoltageDropInput
from ..models.review import (
    AssessmentStatus,
    EvaluationMethod,
    ReviewAssessment,
    ReviewContext,
    ReviewFinding,
)
from ..utils.thermal_solver import ThermalPlaneSpec, solve_plane_temperature


@dataclass(frozen=True, slots=True)
class ComponentStressContract:
    """Explicit component operating conditions versus manufacturer ratings."""

    reference: str
    parameter: str  # "voltage", "current", "power", "vds", "id", "vr", "if"
    rated_value: float | None = None  # Absolute Maximum Rating (AMR)
    recommended_max: float | None = None  # Recommended Operating Condition (ROC)
    nominal_operating: float | None = None  # Typical condition
    worst_case_operating: float | None = None  # Worst-case condition
    derating_limit_ratio: float = 0.80  # Default derating factor (0.80 = 80%)
    units: str = "V"


def evaluate_component_stress(
    contract: ComponentStressContract,
) -> tuple[AssessmentStatus, str, str | None, dict[str, Any]]:
    """Evaluate stress for one component parameter, decoupling ROC and AMR limits."""
    # Check for missing operating conditions
    has_worst_case = contract.worst_case_operating is not None
    has_nominal = contract.nominal_operating is not None

    if not has_worst_case and not has_nominal:
        return (
            AssessmentStatus.NOT_ASSESSED,
            f"Component '{contract.reference}' {contract.parameter} has no operating value.",
            "missing_inputs",
            {"missing_inputs": ["operating_value"]},
        )

    # Check for missing manufacturer ratings
    if contract.rated_value is None and contract.recommended_max is None:
        return (
            AssessmentStatus.NOT_ASSESSED,
            f"Component '{contract.reference}' {contract.parameter} has no rating/limits declared.",
            "missing_inputs",
            {"missing_inputs": ["rated_value"]},
        )

    operating_val = contract.worst_case_operating if has_worst_case else contract.nominal_operating
    if operating_val is None:
        return (
            AssessmentStatus.NOT_ASSESSED,
            f"Component '{contract.reference}' {contract.parameter} operating value unresolved.",
            "missing_inputs",
            {"missing_inputs": ["operating_value"]},
        )

    meta: dict[str, Any] = {
        "parameter": contract.parameter,
        "operating_value": operating_val,
        "is_worst_case": has_worst_case,
        "analysis_type": "worst_case" if has_worst_case else "typical_only",
    }

    # 1. Absolute Maximum Rating (AMR) Overstress Check -> FAIL
    if contract.rated_value is not None and operating_val > contract.rated_value:
        utilization_pct = (operating_val / contract.rated_value) * 100.0
        meta["utilization_pct"] = round(utilization_pct, 1)
        meta["rated_value"] = contract.rated_value
        return (
            AssessmentStatus.FAIL,
            (
                f"Component '{contract.reference}' {contract.parameter} "
                f"({operating_val:g} {contract.units}) EXCEEDS Absolute Maximum Rating "
                f"({contract.rated_value:g} {contract.units}, {utilization_pct:.1f}%) — "
                "overstress damage hazard."
            ),
            "overstress",
            meta,
        )

    # 2. Recommended Operating Condition / Derating Limit Check -> WARN
    derated_limit = (
        contract.recommended_max
        if contract.recommended_max is not None
        else (
            contract.rated_value * contract.derating_limit_ratio if contract.rated_value else None
        )
    )

    if derated_limit is not None:
        meta["derated_limit"] = derated_limit
        if operating_val > derated_limit:
            util_pct = (
                (operating_val / contract.rated_value) * 100.0 if contract.rated_value else 100.0
            )
            meta["utilization_pct"] = round(util_pct, 1)
            return (
                AssessmentStatus.WARN,
                (
                    f"Component '{contract.reference}' {contract.parameter} "
                    f"({operating_val:g} {contract.units}) exceeds safe derating limit "
                    f"({derated_limit:g} {contract.units}) — reliability/lifecycle risk."
                ),
                "derating_exceeded",
                meta,
            )

    return (
        AssessmentStatus.PASS,
        (
            f"Component '{contract.reference}' {contract.parameter} "
            f"({operating_val:g} {contract.units}) is within safe limit "
            f"({derated_limit:g} {contract.units})."
        ),
        None,
        meta,
    )


def evaluate_component_derating(
    context: ReviewContext,
    contracts: list[ComponentStressContract] | None = None,
) -> ReviewAssessment:
    """Evaluate component stress and derating contracts for the active design."""
    resolved_contracts = contracts
    if resolved_contracts is None:
        raw = context.explicit_requirements.get("component_stress_contracts")
        if isinstance(raw, list):
            resolved_contracts = [
                c if isinstance(c, ComponentStressContract) else ComponentStressContract(**c)
                for c in raw
            ]

    if resolved_contracts is None:
        return ReviewAssessment(
            rule_id="electrical.component_derating",
            rule_revision=1,
            status=AssessmentStatus.BLOCKED,
            method=EvaluationMethod.ANALYTICAL,
            summary="Component stress requirements missing; cannot evaluate derating.",
            missing_inputs=["component_operating_points", "component_ratings"],
            metadata={"defect_category": "electrical"},
        )

    if len(resolved_contracts) == 0:
        return ReviewAssessment(
            rule_id="electrical.component_derating",
            rule_revision=1,
            status=AssessmentStatus.NOT_ASSESSED,
            method=EvaluationMethod.ANALYTICAL,
            summary="No component stress contracts declared; derating cannot be assessed.",
            missing_inputs=["component_operating_points"],
            metadata={"defect_category": "electrical", "contract_count": 0},
        )

    findings: list[ReviewFinding] = []
    finding_idx = 1
    unassessed_count = 0

    for c in resolved_contracts:
        status, message, code, meta = evaluate_component_stress(c)
        if status == AssessmentStatus.FAIL:
            findings.append(
                ReviewFinding(
                    id=f"ELEC_DERATE_{finding_idx:03d}",
                    rule_id="electrical.component_derating",
                    rule_revision=1,
                    severity="error",
                    object_ref=c.reference,
                    description=message,
                    measured_value=meta.get("operating_value"),
                    expected_value=c.rated_value,
                    units=c.units,
                    remediation="Select a higher-rated component or reduce operating stress.",
                    metadata=meta,
                )
            )
            finding_idx += 1
        elif status == AssessmentStatus.WARN:
            findings.append(
                ReviewFinding(
                    id=f"ELEC_DERATE_{finding_idx:03d}",
                    rule_id="electrical.component_derating",
                    rule_revision=1,
                    severity="warning",
                    object_ref=c.reference,
                    description=message,
                    measured_value=meta.get("operating_value"),
                    expected_value=meta.get("derated_limit"),
                    units=c.units,
                    remediation="Select component with greater derating margin for reliability.",
                    metadata=meta,
                )
            )
            finding_idx += 1
        elif status == AssessmentStatus.NOT_ASSESSED:
            unassessed_count += 1

    has_error = any(f.severity == "error" for f in findings)
    has_warning = any(f.severity == "warning" for f in findings)

    if has_error:
        overall_status = AssessmentStatus.FAIL
        summary = (
            f"Component derating review failed with {len(findings)} overstress/derating violations."
        )
    elif has_warning:
        overall_status = AssessmentStatus.WARN
        summary = f"Component derating identified {len(findings)} components near rating limits."
    elif unassessed_count > 0:
        overall_status = AssessmentStatus.NOT_ASSESSED
        summary = f"{unassessed_count} component contracts lack operating or rating inputs."
    else:
        overall_status = AssessmentStatus.PASS
        summary = f"All {len(resolved_contracts)} components operate within derating limits."

    return ReviewAssessment(
        rule_id="electrical.component_derating",
        rule_revision=1,
        status=overall_status,
        method=EvaluationMethod.ANALYTICAL,
        summary=summary,
        findings=findings,
        metadata={
            "defect_category": "electrical",
            "contract_count": len(resolved_contracts),
            "unassessed_count": unassessed_count,
        },
    )


def evaluate_trace_dc_loss(
    context: ReviewContext,
    trace_input: VoltageDropInput | None,
    *,
    net_name: str = "VCC",
    max_drop_mv: float = 50.0,
) -> ReviewAssessment:
    """Evaluate power trace DC resistance, voltage drop, and power loss."""
    if trace_input is None:
        return ReviewAssessment(
            rule_id="electrical.trace_voltage_drop",
            rule_revision=1,
            status=AssessmentStatus.BLOCKED,
            method=EvaluationMethod.ANALYTICAL,
            summary="Trace geometry and current inputs missing; cannot evaluate voltage drop.",
            missing_inputs=["trace_current_a", "trace_geometry"],
            metadata={"defect_category": "electrical", "net_name": net_name},
        )

    # Physical validity range check: non-positive current or geometry cannot return PASS
    if (
        trace_input.current_a <= 0.0
        or trace_input.trace_width_mm <= 0.0
        or trace_input.trace_length_mm <= 0.0
        or trace_input.copper_oz <= 0.0
    ):
        return ReviewAssessment(
            rule_id="electrical.trace_voltage_drop",
            rule_revision=1,
            status=AssessmentStatus.NOT_ASSESSED,
            method=EvaluationMethod.ANALYTICAL,
            summary=(
                "Trace geometry or current outside physical validity range; "
                "cannot assess voltage drop."
            ),
            missing_inputs=["valid_physical_inputs"],
            metadata={"defect_category": "electrical", "net_name": net_name},
        )

    # Standard copper resistivity: 1.7e-8 ohm*m at 20 C
    thickness_m = trace_input.copper_oz * 0.0348e-3
    length_m = trace_input.trace_length_mm * 1e-3
    width_m = trace_input.trace_width_mm * 1e-3
    resistance_ohm = (1.7e-8 / thickness_m) * (length_m / width_m)

    drop_mv = trace_input.current_a * resistance_ohm * 1000.0
    power_loss_mw = (trace_input.current_a**2) * resistance_ohm * 1000.0

    findings: list[ReviewFinding] = []
    if drop_mv > max_drop_mv:
        status = AssessmentStatus.FAIL
        summary = (
            f"Trace DC voltage drop ({drop_mv:.1f} mV) on net '{net_name}' exceeds "
            f"limit ({max_drop_mv:.1f} mV)."
        )
        findings.append(
            ReviewFinding(
                id="TRACE_VDROP_001",
                rule_id="electrical.trace_voltage_drop",
                rule_revision=1,
                severity="error",
                net=net_name,
                description=summary,
                measured_value=round(drop_mv, 2),
                expected_value=max_drop_mv,
                units="mV",
                remediation="Widen power trace, shorten route, or increase copper ounce weight.",
                metadata={
                    "drop_mv": round(drop_mv, 2),
                    "resistance_mohm": round(resistance_ohm * 1000.0, 2),
                    "power_loss_mw": round(power_loss_mw, 2),
                },
            )
        )
    else:
        status = AssessmentStatus.PASS
        summary = (
            f"Trace DC drop ({drop_mv:.1f} mV) and power loss ({power_loss_mw:.1f} mW) "
            f"are within limit ({max_drop_mv:.1f} mV)."
        )

    return ReviewAssessment(
        rule_id="electrical.trace_voltage_drop",
        rule_revision=1,
        status=status,
        method=EvaluationMethod.ANALYTICAL,
        summary=summary,
        findings=findings,
        metadata={
            "defect_category": "electrical",
            "net_name": net_name,
            "drop_mv": round(drop_mv, 2),
            "resistance_mohm": round(resistance_ohm * 1000.0, 2),
            "power_loss_mw": round(power_loss_mw, 2),
        },
    )


def evaluate_thermal_spreading(
    context: ReviewContext,
    spec: ThermalPlaneSpec | None,
    *,
    max_peak_temp_c: float = 85.0,
) -> ReviewAssessment:
    """Evaluate 2-D steady-state heat spreading on copper plane with physical validity guards."""
    if spec is None:
        return ReviewAssessment(
            rule_id="thermal.plane_operating_temperature",
            rule_revision=1,
            status=AssessmentStatus.BLOCKED,
            method=EvaluationMethod.ANALYTICAL,
            summary="Thermal plane specification missing; cannot evaluate copper temperature.",
            missing_inputs=["thermal_plane_spec"],
            metadata={"defect_category": "thermal"},
        )

    # Physical validity range: source cannot exceed plane, power must be positive
    if (
        spec.source_width_mm > spec.plane_width_mm
        or spec.source_height_mm > spec.plane_height_mm
        or spec.plane_width_mm <= 0.0
        or spec.plane_height_mm <= 0.0
    ):
        return ReviewAssessment(
            rule_id="thermal.plane_operating_temperature",
            rule_revision=1,
            status=AssessmentStatus.NOT_ASSESSED,
            method=EvaluationMethod.ANALYTICAL,
            summary="Heat source dimensions exceed copper plane; solver assumptions violated.",
            missing_inputs=["valid_plane_geometry"],
            metadata={"defect_category": "thermal"},
        )

    if spec.power_w <= 0.0:
        return ReviewAssessment(
            rule_id="thermal.plane_operating_temperature",
            rule_revision=1,
            status=AssessmentStatus.NOT_ASSESSED,
            method=EvaluationMethod.ANALYTICAL,
            summary="Thermal power dissipation is zero or negative; solve not assessed.",
            missing_inputs=["positive_power"],
            metadata={"defect_category": "thermal"},
        )

    try:
        result = solve_plane_temperature(spec, max_cells_per_side=24, max_iterations=5000)
    except Exception as exc:
        return ReviewAssessment(
            rule_id="thermal.plane_operating_temperature",
            rule_revision=1,
            status=AssessmentStatus.NOT_ASSESSED,
            method=EvaluationMethod.ANALYTICAL,
            summary=f"Thermal numerical solver error: {exc}",
            missing_inputs=["solver_convergence"],
            metadata={"defect_category": "thermal", "error": str(exc)},
        )

    if not result.converged:
        return ReviewAssessment(
            rule_id="thermal.plane_operating_temperature",
            rule_revision=1,
            status=AssessmentStatus.NOT_ASSESSED,
            method=EvaluationMethod.ANALYTICAL,
            summary="Thermal solver did not converge; cannot establish thermal acceptance.",
            missing_inputs=["solver_convergence"],
            metadata={"defect_category": "thermal", "iterations": result.iterations},
        )

    findings: list[ReviewFinding] = []
    if result.peak_temp_c > max_peak_temp_c:
        diff_c = result.peak_temp_c - max_peak_temp_c
        status = AssessmentStatus.FAIL
        summary = (
            f"Peak copper temperature ({result.peak_temp_c:.1f} °C) exceeds "
            f"limit ({max_peak_temp_c:.1f} °C) by {diff_c:.1f} °C."
        )
        findings.append(
            ReviewFinding(
                id="THERM_PEAK_001",
                rule_id="thermal.plane_operating_temperature",
                rule_revision=1,
                severity="error",
                description=summary,
                measured_value=round(result.peak_temp_c, 1),
                expected_value=max_peak_temp_c,
                units="C",
                remediation=(
                    "Increase copper weight to 2oz, enlarge plane area, or add thermal vias."
                ),
                metadata={
                    "peak_temp_c": round(result.peak_temp_c, 1),
                    "peak_rise_c": round(result.peak_rise_c, 1),
                    "ambient_c": spec.ambient_c,
                    "power_w": spec.power_w,
                },
            )
        )
    else:
        status = AssessmentStatus.PASS
        summary = (
            f"Peak temperature ({result.peak_temp_c:.1f} °C, rise {result.peak_rise_c:.1f} °C) "
            f"is safely below {max_peak_temp_c:.1f} °C limit."
        )

    return ReviewAssessment(
        rule_id="thermal.plane_operating_temperature",
        rule_revision=1,
        status=status,
        method=EvaluationMethod.ANALYTICAL,
        summary=summary,
        findings=findings,
        metadata={
            "defect_category": "thermal",
            "peak_temp_c": round(result.peak_temp_c, 1),
            "peak_rise_c": round(result.peak_rise_c, 1),
            "ambient_c": spec.ambient_c,
            "power_w": spec.power_w,
        },
    )


def evaluate_specialist_safety_review(
    context: ReviewContext,
    *,
    voltage_v: float,
    has_specialist_signoff: bool = False,
    specialist_evidence_id: str | None = None,
) -> ReviewAssessment:
    """Explicitly verify high-voltage / hazardous mains insulation with specialist review."""
    if voltage_v >= 50.0:
        if not has_specialist_signoff:
            return ReviewAssessment(
                rule_id="safety.hazardous_mains_clearance",
                rule_revision=1,
                status=AssessmentStatus.FAIL,
                method=EvaluationMethod.HUMAN_REVIEW,
                summary=(
                    f"Hazardous voltage ({voltage_v:g} V) requires explicit specialist insulation "
                    "and physical measurement review (IEC 62368-1). Automated clearance checks "
                    "cannot return PASS."
                ),
                findings=[
                    ReviewFinding(
                        id="SAFETY_HV_001",
                        rule_id="safety.hazardous_mains_clearance",
                        rule_revision=1,
                        severity="error",
                        description=(
                            f"Mains/HV ({voltage_v:g} V) lacks approved specialist safety sign-off."
                        ),
                        remediation=(
                            "Conduct certified specialist insulation review and attach evidence ID."
                        ),
                        metadata={"voltage_v": voltage_v, "requires_human_review": True},
                    )
                ],
                metadata={"voltage_v": voltage_v, "requires_human_review": True},
            )

        evidence_list = [specialist_evidence_id] if specialist_evidence_id else []
        return ReviewAssessment(
            rule_id="safety.hazardous_mains_clearance",
            rule_revision=1,
            status=AssessmentStatus.PASS,
            method=EvaluationMethod.HUMAN_REVIEW,
            summary=f"Specialist safety review approved for {voltage_v:g} V hazardous circuit.",
            evidence_refs=evidence_list,
            metadata={"voltage_v": voltage_v, "specialist_approved": True},
        )

    return ReviewAssessment(
        rule_id="safety.hazardous_mains_clearance",
        rule_revision=1,
        status=AssessmentStatus.NOT_APPLICABLE,
        method=EvaluationMethod.HUMAN_REVIEW,
        summary=(
            f"Operating voltage ({voltage_v:g} V) is within SELV limits (<50 V); "
            "mains rule not applicable."
        ),
        metadata={"voltage_v": voltage_v, "is_selv": True},
    )

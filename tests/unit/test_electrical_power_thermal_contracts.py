"""Unit tests for electrical, power, derating, and thermal review contracts (#1584, T7)."""

from __future__ import annotations

from kicad_mcp.models.power_integrity import VoltageDropInput
from kicad_mcp.models.review import (
    AssessmentStatus,
    EvaluationMethod,
    ReviewContext,
)
from kicad_mcp.review.electrical_contracts import (
    ComponentStressContract,
    evaluate_component_derating,
    evaluate_component_stress,
    evaluate_specialist_safety_review,
    evaluate_thermal_spreading,
    evaluate_trace_dc_loss,
)
from kicad_mcp.utils.thermal_solver import ThermalPlaneSpec


def test_missing_operating_conditions_evaluates_not_assessed() -> None:
    """Missing load/environment or component ratings must evaluate to NOT_ASSESSED, never PASS."""
    # 1. Missing operating values
    contract_no_op = ComponentStressContract(
        reference="C1",
        parameter="voltage",
        rated_value=25.0,
    )
    status, msg, code, meta = evaluate_component_stress(contract_no_op)
    assert status == AssessmentStatus.NOT_ASSESSED
    assert "no operating value" in msg

    # 2. Missing ratings
    contract_no_rating = ComponentStressContract(
        reference="C1",
        parameter="voltage",
        nominal_operating=12.0,
    )
    status, msg, code, meta = evaluate_component_stress(contract_no_rating)
    assert status == AssessmentStatus.NOT_ASSESSED
    assert "no rating/limits declared" in msg


def test_amr_and_roc_limits_not_conflated() -> None:
    """Recommended operating limits (derating) and AMR are strictly separated."""
    # Rated 25V, derating factor 0.80 -> safe limit is 20.0V

    # A) Safe: 15V operating -> PASS
    c_safe = ComponentStressContract(
        reference="C1",
        parameter="voltage",
        rated_value=25.0,
        derating_limit_ratio=0.80,
        nominal_operating=15.0,
    )
    status, msg, code, meta = evaluate_component_stress(c_safe)
    assert status == AssessmentStatus.PASS

    # B) Derating warning: 22V operating (>20V derating, but <25V AMR) -> WARN (not FAIL)
    c_warn = ComponentStressContract(
        reference="C1",
        parameter="voltage",
        rated_value=25.0,
        derating_limit_ratio=0.80,
        worst_case_operating=22.0,
    )
    status, msg, code, meta = evaluate_component_stress(c_warn)
    assert status == AssessmentStatus.WARN
    assert code == "derating_exceeded"
    assert "exceeds safe derating limit" in msg

    # C) AMR overstress: 28V operating (>25V AMR) -> FAIL
    c_fail = ComponentStressContract(
        reference="C1",
        parameter="voltage",
        rated_value=25.0,
        derating_limit_ratio=0.80,
        worst_case_operating=28.0,
    )
    status, msg, code, meta = evaluate_component_stress(c_fail)
    assert status == AssessmentStatus.FAIL
    assert code == "overstress"
    assert "EXCEEDS Absolute Maximum Rating" in msg


def test_typical_only_distinguished_from_worst_case() -> None:
    """Typical-only calculations record explicit metadata; cannot claim worst-case bounds."""
    contract_typical = ComponentStressContract(
        reference="R1",
        parameter="power",
        rated_value=0.25,
        nominal_operating=0.10,
    )
    _, _, _, meta_typ = evaluate_component_stress(contract_typical)
    assert meta_typ["analysis_type"] == "typical_only"
    assert meta_typ["is_worst_case"] is False

    contract_worst = ComponentStressContract(
        reference="R1",
        parameter="power",
        rated_value=0.25,
        worst_case_operating=0.15,
    )
    _, _, _, meta_wc = evaluate_component_stress(contract_worst)
    assert meta_wc["analysis_type"] == "worst_case"
    assert meta_wc["is_worst_case"] is True


def test_component_derating_assessment_aggregation() -> None:
    """Aggregates multiple contracts into ReviewAssessment with proper finding severities."""
    context = ReviewContext(project_name="derating_test")
    contracts = [
        ComponentStressContract(
            reference="C1",
            parameter="voltage",
            rated_value=25.0,
            derating_limit_ratio=0.80,
            worst_case_operating=15.0,  # PASS
        ),
        ComponentStressContract(
            reference="R1",
            parameter="power",
            rated_value=0.25,
            derating_limit_ratio=0.60,
            worst_case_operating=0.18,  # >0.15W -> WARN
        ),
        ComponentStressContract(
            reference="Q1",
            parameter="vds",
            rated_value=30.0,
            worst_case_operating=35.0,  # >30V -> FAIL
        ),
    ]

    assessment = evaluate_component_derating(context, contracts)
    assert assessment.status == AssessmentStatus.FAIL
    assert len(assessment.findings) == 2  # 1 warning + 1 error

    severities = {f.object_ref: f.severity for f in assessment.findings}
    assert severities["R1"] == "warning"
    assert severities["Q1"] == "error"


def test_trace_dc_loss_solver_validity_and_drop() -> None:
    """Validates trace DC drop and rejects non-physical inputs without passing."""
    context = ReviewContext(project_name="dc_drop")

    # Test valid pass: 0.5A on 1mm wide 50mm trace (1oz)
    valid_pass = VoltageDropInput(
        current_a=0.5,
        trace_width_mm=1.0,
        trace_length_mm=50.0,
        copper_oz=1.0,
    )
    res_pass = evaluate_trace_dc_loss(context, valid_pass, max_drop_mv=50.0)
    assert res_pass.status == AssessmentStatus.PASS
    assert len(res_pass.findings) == 0

    # High drop failure: 5A on 0.2mm wide 200mm trace -> >1000 mV drop
    high_drop = VoltageDropInput(
        current_a=5.0,
        trace_width_mm=0.2,
        trace_length_mm=200.0,
        copper_oz=1.0,
    )
    res_fail = evaluate_trace_dc_loss(context, high_drop, max_drop_mv=50.0)
    assert res_fail.status == AssessmentStatus.FAIL
    assert len(res_fail.findings) == 1
    assert res_fail.findings[0].severity == "error"


def test_thermal_spreading_solver_validity_and_solution() -> None:
    """Evaluates thermal spreading and prevents non-physical solver inputs from passing."""
    context = ReviewContext(project_name="thermal_test")

    # Invalid geometry: source larger than plane -> NOT_ASSESSED
    invalid_spec = ThermalPlaneSpec(
        power_w=2.0,
        plane_width_mm=10.0,
        plane_height_mm=10.0,
        source_width_mm=15.0,  # Larger than plane!
        source_height_mm=5.0,
    )
    eval_invalid = evaluate_thermal_spreading(context, invalid_spec)
    assert eval_invalid.status == AssessmentStatus.NOT_ASSESSED
    assert "solver assumptions violated" in eval_invalid.summary

    # Valid plane: 1.0W into 50x50 mm plane with 1oz copper
    valid_spec = ThermalPlaneSpec(
        power_w=1.0,
        plane_width_mm=50.0,
        plane_height_mm=50.0,
        source_width_mm=5.0,
        source_height_mm=5.0,
        ambient_c=25.0,
    )
    eval_valid = evaluate_thermal_spreading(context, valid_spec, max_peak_temp_c=100.0)
    assert eval_valid.status == AssessmentStatus.PASS
    assert eval_valid.metadata.get("peak_temp_c") is not None


def test_specialist_safety_review_guard() -> None:
    """HV / hazardous mains requires specialist review; heuristics cannot return PASS."""
    context = ReviewContext(project_name="safety_test")

    # 230V mains without specialist review -> FAIL
    hv_unreviewed = evaluate_specialist_safety_review(
        context,
        voltage_v=230.0,
        has_specialist_signoff=False,
    )
    assert hv_unreviewed.status == AssessmentStatus.FAIL
    assert hv_unreviewed.method == EvaluationMethod.HUMAN_REVIEW
    assert "requires explicit specialist insulation" in hv_unreviewed.summary

    # 230V mains with certified specialist review -> PASS
    hv_approved = evaluate_specialist_safety_review(
        context,
        voltage_v=230.0,
        has_specialist_signoff=True,
        specialist_evidence_id="EVID_IEC62368_SIGNOFF_20261103",
    )
    assert hv_approved.status == AssessmentStatus.PASS
    assert hv_approved.evidence_refs == ["EVID_IEC62368_SIGNOFF_20261103"]

    # Low-voltage SELV (3.3V) -> NOT_APPLICABLE
    lv_selv = evaluate_specialist_safety_review(context, voltage_v=3.3)
    assert lv_selv.status == AssessmentStatus.NOT_APPLICABLE

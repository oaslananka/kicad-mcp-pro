"""Unit tests for the engineering review rule catalog and context-aware assessment model (#1579).

Validates:
- Typed, validated domain records and rule revisions.
- Explicit applicability resolution, reasons, and missing inputs.
- Unknown/conflicting context remains UNDETERMINED.
- Required NOT_ASSESSED/BLOCKED never adapts to PASS.
- Unit compatibility checks across physical dimensions (no invalid cross-dimension coercion).
- Rejection of duplicate revisions and source/domain conflicts.
- Legacy verdict.v1 envelope compatibility and round-trip consistency.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from kicad_mcp.models.review import (
    AssessmentStatus,
    EvaluationMethod,
    ResolvedReviewRule,
    ReviewAssessment,
    ReviewContext,
    ReviewDomain,
    ReviewFinding,
    ReviewRule,
    ReviewSnapshot,
    RuleApplicability,
    validate_unit_compatibility,
)
from kicad_mcp.models.verdict import VerdictReport
from kicad_mcp.review.adapter import (
    adapt_assessment_to_verdict,
    adapt_snapshot_to_verdict,
)
from kicad_mcp.review.catalog import (
    ReviewRuleCatalog,
    build_standard_rule_catalog,
    compute_coverage,
)


def test_review_rule_validation() -> None:
    """Verifies ReviewRule field validation and constraints."""
    rule = ReviewRule(
        rule_id="routing.orthogonal_corners",
        revision=1,
        domain=ReviewDomain.ROUTING,
        title="PCB 90-Degree Route Corner Style",
        source_doc="Routing Guidelines",
        source_revision="2026.1",
        required_inputs=["tracks"],
        units="count",
        method=EvaluationMethod.HEURISTIC,
        severity="warning",
        is_mandatory=False,
    )
    assert rule.rule_id == "routing.orthogonal_corners"
    assert rule.revision == 1
    assert rule.units == "count"

    # Invalid unit must be rejected
    with pytest.raises(ValidationError):
        ReviewRule(
            rule_id="test.invalid_unit",
            revision=1,
            domain=ReviewDomain.PCB,
            title="Invalid Unit Rule",
            source_doc="Doc",
            source_revision="1",
            units="lightyears_per_gallon",
            method=EvaluationMethod.ANALYTICAL,
        )

    # Invalid rule_id pattern must be rejected
    with pytest.raises(ValidationError):
        ReviewRule(
            rule_id="Invalid Rule Id With Spaces",
            revision=1,
            domain=ReviewDomain.PCB,
            title="Bad ID",
            source_doc="Doc",
            source_revision="1",
            method=EvaluationMethod.ANALYTICAL,
        )


def test_unit_compatibility_validation() -> None:
    """Ensures incompatible physical dimensions cannot be coerced or compared."""
    # Compatible units share same dimension
    validate_unit_compatibility("mm", "um")
    validate_unit_compatibility("V", "mV")
    validate_unit_compatibility("A", "mA")
    validate_unit_compatibility("ps", "ns")

    # Incompatible units must raise ValueError
    msg = "Cannot coerce or compare incompatible physical dimensions"
    with pytest.raises(ValueError, match=msg):
        validate_unit_compatibility("mm", "V")

    with pytest.raises(ValueError, match=msg):
        validate_unit_compatibility("ps", "A")

    # Unrecognized unit must raise ValueError
    with pytest.raises(ValueError, match="Unrecognized unit"):
        validate_unit_compatibility("mm", "unknown_unit_xyz")


def test_review_context_inferred_vs_explicit() -> None:
    """Verifies that inferred values remain explicitly marked."""
    ctx = ReviewContext(
        project_name="motor_controller",
        maturity="prototype",
        technical_domains=["power_electronics"],
        operating_voltage_v=24.0,
        explicit_requirements={"max_board_temp_c": 85.0},
        inferred_values={"operating_current_a": 5.0},
    )
    assert ctx.operating_voltage_v == 24.0
    assert not ctx.is_inferred("max_board_temp_c")
    assert ctx.is_inferred("operating_current_a")


def test_catalog_rejection_of_duplicates_and_conflicts() -> None:
    """Verifies that catalog rejects duplicate revisions and domain changes."""
    catalog = ReviewRuleCatalog()
    rule_v1 = ReviewRule(
        rule_id="pcb.clearance",
        revision=1,
        domain=ReviewDomain.PCB,
        title="PCB Clearance",
        source_doc="Doc",
        source_revision="1",
        units="mm",
        method=EvaluationMethod.ANALYTICAL,
    )
    catalog.register(rule_v1)

    # Registering duplicate (id, revision) must raise ValueError
    with pytest.raises(ValueError, match="is registered"):
        catalog.register(rule_v1)

    # Registering v2 with altered domain must raise ValueError
    rule_v2_conflict = ReviewRule(
        rule_id="pcb.clearance",
        revision=2,
        domain=ReviewDomain.SCHEMATIC,  # Changed domain!
        title="PCB Clearance",
        source_doc="Doc",
        source_revision="2",
        units="mm",
        method=EvaluationMethod.ANALYTICAL,
    )
    with pytest.raises(ValueError, match="Conflicting rule revision"):
        catalog.register(rule_v2_conflict)


def test_applicability_resolution_for_hazardous_mains() -> None:
    """Verifies honest applicability resolution for safety rules."""
    catalog = build_standard_rule_catalog()

    # 1. Low-voltage project -> NOT_APPLICABLE
    lv_context = ReviewContext(
        is_hv=False,
        operating_voltage_v=3.3,
        technical_domains=["low_power"],
    )
    resolved_lv = {r.rule.rule_id: r for r in catalog.resolve(lv_context)}
    assert (
        resolved_lv["safety.hazardous_mains_clearance"].status == RuleApplicability.NOT_APPLICABLE
    )

    # 2. Conflicting context (is_hv=True but voltage < 50V) -> UNDETERMINED
    conflict_context = ReviewContext(
        is_hv=True,
        operating_voltage_v=12.0,
        technical_domains=["hazardous_mains"],
    )
    resolved_conflict = {r.rule.rule_id: r for r in catalog.resolve(conflict_context)}
    assert (
        resolved_conflict["safety.hazardous_mains_clearance"].status
        == RuleApplicability.UNDETERMINED
    )
    assert "Conflicting context" in resolved_conflict["safety.hazardous_mains_clearance"].rationale

    # 3. High-voltage project with missing pad spacing input -> UNDETERMINED
    hv_context = ReviewContext(
        is_hv=True,
        operating_voltage_v=230.0,
        technical_domains=["hazardous_mains"],
    )
    resolved_hv = {r.rule.rule_id: r for r in catalog.resolve(hv_context)}
    assert resolved_hv["safety.hazardous_mains_clearance"].status == RuleApplicability.UNDETERMINED
    assert "pad_spacing_mm" in resolved_hv["safety.hazardous_mains_clearance"].missing_inputs

    # 4. High-voltage project with all inputs provided -> APPLICABLE
    hv_complete_context = ReviewContext(
        is_hv=True,
        operating_voltage_v=230.0,
        technical_domains=["hazardous_mains"],
        explicit_requirements={"pad_spacing_mm": 3.0},
    )
    resolved_complete = {r.rule.rule_id: r for r in catalog.resolve(hv_complete_context)}
    assert (
        resolved_complete["safety.hazardous_mains_clearance"].status == RuleApplicability.APPLICABLE
    )


def test_applicability_resolution_for_routing_style() -> None:
    """Verifies that declared routing style policy resolves properly."""
    catalog = build_standard_rule_catalog()

    # Orthogonal explicitly permitted -> NOT_APPLICABLE
    context_permits = ReviewContext(declared_routing_style="orthogonal_allowed")
    resolved = {r.rule.rule_id: r for r in catalog.resolve(context_permits)}
    assert resolved["routing.orthogonal_corners"].status == RuleApplicability.NOT_APPLICABLE

    # Default project -> APPLICABLE with advisory threshold
    context_default = ReviewContext()
    resolved_default = {r.rule.rule_id: r for r in catalog.resolve(context_default)}
    assert resolved_default["routing.orthogonal_corners"].status == RuleApplicability.APPLICABLE


def test_adapter_never_adapts_not_assessed_or_blocked_to_pass() -> None:
    """Critical safety test: NOT_ASSESSED and BLOCKED must NEVER adapt to verdict='PASS'."""
    mandatory_rule = ReviewRule(
        rule_id="safety.mains",
        revision=1,
        domain=ReviewDomain.SAFETY,
        title="Mains Safety",
        source_doc="Doc",
        source_revision="1",
        method=EvaluationMethod.ANALYTICAL,
        is_mandatory=True,
    )

    # Mandatory NOT_ASSESSED -> FAIL (never PASS)
    not_assessed = ReviewAssessment(
        rule_id="safety.mains",
        status=AssessmentStatus.NOT_ASSESSED,
        method=EvaluationMethod.ANALYTICAL,
        summary="No insulation measurement executed.",
        missing_inputs=["insulation_barrier_mm"],
    )
    v_not_assessed = adapt_assessment_to_verdict(not_assessed, mandatory_rule)
    assert v_not_assessed.verdict == "FAIL"
    assert v_not_assessed.severity == "error"
    assert v_not_assessed.verdict != "PASS"
    assert "NOT ASSESSED" in v_not_assessed.summary

    # BLOCKED -> FAIL (never PASS)
    blocked = ReviewAssessment(
        rule_id="safety.mains",
        status=AssessmentStatus.BLOCKED,
        method=EvaluationMethod.ANALYTICAL,
        summary="Solver backend crashed.",
        missing_inputs=["solver_process"],
    )
    v_blocked = adapt_assessment_to_verdict(blocked, mandatory_rule)
    assert v_blocked.verdict == "FAIL"
    assert v_blocked.severity == "error"
    assert v_blocked.verdict != "PASS"
    assert "BLOCKED" in v_blocked.summary

    # Non-mandatory NOT_ASSESSED -> WARN (never PASS)
    advisory_rule = ReviewRule(
        rule_id="style.advisory",
        revision=1,
        domain=ReviewDomain.ROUTING,
        title="Style Advisory",
        source_doc="Doc",
        source_revision="1",
        method=EvaluationMethod.HEURISTIC,
        is_mandatory=False,
    )
    v_advisory = adapt_assessment_to_verdict(not_assessed, advisory_rule)
    assert v_advisory.verdict == "WARN"
    assert v_advisory.verdict != "PASS"

    # PASS -> PASS
    passed = ReviewAssessment(
        rule_id="safety.mains",
        status=AssessmentStatus.PASS,
        method=EvaluationMethod.ANALYTICAL,
        summary="Clearance 5.2 mm satisfies 3.0 mm minimum.",
    )
    v_pass = adapt_assessment_to_verdict(passed, mandatory_rule)
    assert v_pass.verdict == "PASS"


def test_coverage_and_snapshot_aggregation() -> None:
    """Verifies coverage metric calculation and snapshot aggregation."""
    catalog = build_standard_rule_catalog()
    ctx = ReviewContext(
        project_name="demo_board",
        explicit_requirements={
            "tracks": True,
            "supply_net": "+3.3V",
            "power_pad_positions": True,
            "selected_mfg_profile": "JLCPCB",
            "pth_pads": True,
            "connector_mating_specs": True,
            "board_outline": True,
            "schematic_symbols": True,
            "schematic_wires": True,
        },
    )
    resolved = catalog.resolve(ctx)

    # Leave placement.decoupling_pin_connectivity unassessed
    assessments = [
        ReviewAssessment(
            rule_id="routing.orthogonal_corners",
            status=AssessmentStatus.PASS,
            method=EvaluationMethod.HEURISTIC,
            summary="No 90-degree corners.",
        ),
        ReviewAssessment(
            rule_id="dfm.circular_pth_annular_ring",
            status=AssessmentStatus.PASS,
            method=EvaluationMethod.ANALYTICAL,
            summary="All rings >= 0.15 mm.",
        ),
    ]

    coverage = compute_coverage(resolved, assessments)
    assert coverage.total_rules == len(resolved)
    assert coverage.passed_count == 2
    # Mandatory rule 'placement.decoupling_pin_connectivity' was not assessed
    assert "placement.decoupling_pin_connectivity" in coverage.required_unassessed

    snapshot = ReviewSnapshot(
        project_key="demo_board",
        project_source_sha256="0" * 64,
        rule_catalog_revision="2026.1",
        context=ctx,
        resolved_rules=resolved,
        assessments=assessments,
        coverage=coverage,
    )

    # Because required checks are unassessed, overall verdict MUST be FAIL
    v_snapshot = adapt_snapshot_to_verdict(snapshot)
    assert v_snapshot.verdict == "FAIL"
    assert "unassessed" in v_snapshot.summary


def test_legacy_verdict_roundtrip_compatibility() -> None:
    """Ensures adapted VerdictReport serializes and deserializes as valid verdict.v1 model."""
    assessment = ReviewAssessment(
        rule_id="dfm.circular_pth_annular_ring",
        status=AssessmentStatus.WARN,
        method=EvaluationMethod.ANALYTICAL,
        summary="2 pads close to minimum annular ring.",
        findings=[
            ReviewFinding(
                id="f_annular_01",
                rule_id="dfm.circular_pth_annular_ring",
                severity="warning",
                object_ref="J1",
                pin="1",
                location_mm=(12.5, 34.2),
                description="Annular ring 0.155 mm is near 0.150 mm limit.",
                measured_value=0.155,
                expected_value=0.150,
                units="mm",
                remediation="Increase outer diameter to 1.2 mm.",
            )
        ],
    )

    v_report = adapt_assessment_to_verdict(assessment)
    assert v_report.schema_version == "verdict.v1"
    assert v_report.verdict == "WARN"
    assert len(v_report.findings) == 1
    assert v_report.findings[0].id == "f_annular_01"

    # JSON round-trip
    payload = v_report.model_dump(mode="json")
    reloaded = VerdictReport.model_validate(payload)
    assert reloaded.verdict == "WARN"
    assert reloaded.findings[0].id == "f_annular_01"
    assert reloaded.metadata["rule_id"] == "dfm.circular_pth_annular_ring"


def test_catalog_constructor_with_rules_and_get() -> None:
    """Verifies constructor pre-population and get() behaviors including error paths."""
    r1_v1 = ReviewRule(
        rule_id="pcb.clearance",
        revision=1,
        domain=ReviewDomain.PCB,
        title="PCB Clearance v1",
        source_doc="Doc",
        source_revision="1",
        method=EvaluationMethod.ANALYTICAL,
    )
    r1_v2 = ReviewRule(
        rule_id="pcb.clearance",
        revision=2,
        domain=ReviewDomain.PCB,
        title="PCB Clearance v2",
        source_doc="Doc",
        source_revision="2",
        method=EvaluationMethod.ANALYTICAL,
    )
    r2 = ReviewRule(
        rule_id="routing.orthogonal_corners",
        revision=1,
        domain=ReviewDomain.ROUTING,
        title="Orthogonal Corners",
        source_doc="Doc",
        source_revision="1",
        method=EvaluationMethod.HEURISTIC,
    )

    catalog = ReviewRuleCatalog(rules=[r1_v1, r1_v2, r2])

    # get without revision returns latest revision (2)
    assert catalog.get("pcb.clearance").revision == 2
    # get with specific revision returns that revision
    assert catalog.get("pcb.clearance", revision=1).revision == 1

    # Unknown rule_id raises KeyError
    with pytest.raises(KeyError, match="not found in catalog"):
        catalog.get("nonexistent.rule")

    # Unknown revision for existing rule raises KeyError
    with pytest.raises(KeyError, match="revision 99 was not found"):
        catalog.get("pcb.clearance", revision=99)

    # list_rules domain filter
    pcb_rules = catalog.list_rules(domain=ReviewDomain.PCB)
    assert len(pcb_rules) == 2
    assert all(r.domain == ReviewDomain.PCB for r in pcb_rules)


def test_context_keys_and_coverage_branches() -> None:
    """Exercises additional context fields and coverage calculation statuses."""
    catalog = build_standard_rule_catalog()
    ctx = ReviewContext(
        operating_voltage_v=12.0,
        operating_current_a=3.5,
        selected_mfg_profile="JLCPCB",
        has_kicad_cli=True,
        has_3d_models=True,
    )
    resolved = catalog.resolve(ctx)
    assert len(resolved) > 0

    # Test adapt_assessment_to_verdict with net/layer metadata, NOT_APPLICABLE, and FAIL
    f_detailed = ReviewFinding(
        id="f_detail_01",
        rule_id="routing.orthogonal_corners",
        severity="error",
        object_ref="track_12",
        net="+5V",
        layer="B.Cu",
        description="Corner violation on layer B.Cu",
    )
    fail_assessment = ReviewAssessment(
        rule_id="routing.orthogonal_corners",
        status=AssessmentStatus.FAIL,
        method=EvaluationMethod.HEURISTIC,
        summary="90 degree corner detected.",
        findings=[f_detailed],
    )
    v_fail = adapt_assessment_to_verdict(fail_assessment)
    assert v_fail.verdict == "FAIL"
    assert v_fail.findings[0].metadata["net"] == "+5V"
    assert v_fail.findings[0].metadata["layer"] == "B.Cu"

    na_assessment = ReviewAssessment(
        rule_id="safety.hazardous_mains_clearance",
        status=AssessmentStatus.NOT_APPLICABLE,
        method=EvaluationMethod.ANALYTICAL,
        summary="Not a high-voltage board.",
    )
    v_na = adapt_assessment_to_verdict(na_assessment)
    assert v_na.verdict == "PASS"
    assert "NOT APPLICABLE" in v_na.summary

    # Unhandled status raises ValueError
    mock_bad_enum = MagicMock()
    mock_bad_enum.value = "CUSTOM_UNKNOWN"
    mock_assessment = MagicMock()
    mock_assessment.status = mock_bad_enum
    mock_assessment.rule_id = "test.rule"
    mock_assessment.rule_revision = 1
    mock_assessment.method = EvaluationMethod.ANALYTICAL
    mock_assessment.metadata = {}
    mock_assessment.findings = []

    with pytest.raises(ValueError, match="Unhandled assessment status"):
        adapt_assessment_to_verdict(mock_assessment)


def test_snapshot_warn_and_pass_branches() -> None:
    """Verifies adapt_snapshot_to_verdict when WARN or PASS overall."""
    ctx = ReviewContext(project_name="all_clean")
    r1 = ReviewRule(
        rule_id="test.clean_rule",
        revision=1,
        domain=ReviewDomain.PCB,
        title="Clean Rule",
        source_doc="Doc",
        source_revision="1",
        method=EvaluationMethod.ANALYTICAL,
        is_mandatory=False,
    )
    cat = ReviewRuleCatalog(rules=[r1])
    resolved = cat.resolve(ctx)

    # 1. WARN snapshot
    warn_assessment = ReviewAssessment(
        rule_id="test.clean_rule",
        status=AssessmentStatus.WARN,
        method=EvaluationMethod.ANALYTICAL,
        summary="Advisory warning.",
    )
    cov_warn = compute_coverage(resolved, [warn_assessment])
    snap_warn = ReviewSnapshot(
        project_key="clean_board",
        project_source_sha256="0" * 64,
        rule_catalog_revision="2026.1",
        context=ctx,
        resolved_rules=resolved,
        assessments=[warn_assessment],
        coverage=cov_warn,
    )
    v_snap_warn = adapt_snapshot_to_verdict(snap_warn)
    assert v_snap_warn.verdict == "WARN"
    assert "warnings" in v_snap_warn.summary

    # 2. PASS snapshot
    pass_assessment = ReviewAssessment(
        rule_id="test.clean_rule",
        status=AssessmentStatus.PASS,
        method=EvaluationMethod.ANALYTICAL,
        summary="All clear.",
    )
    cov_pass = compute_coverage(resolved, [pass_assessment])
    snap_pass = ReviewSnapshot(
        project_key="clean_board",
        project_source_sha256="0" * 64,
        rule_catalog_revision="2026.1",
        context=ctx,
        resolved_rules=resolved,
        assessments=[pass_assessment],
        coverage=cov_pass,
    )
    v_snap_pass = adapt_snapshot_to_verdict(snap_pass)
    assert v_snap_pass.verdict == "PASS"
    assert "verified" in v_snap_pass.summary

    # 3. compute_coverage branches: UNDETERMINED resolved rule and BLOCKED assessment
    blocked_assessment = ReviewAssessment(
        rule_id="test.clean_rule",
        status=AssessmentStatus.BLOCKED,
        method=EvaluationMethod.ANALYTICAL,
        summary="Blocked run.",
    )
    fail_assessment = ReviewAssessment(
        rule_id="test.clean_rule",
        status=AssessmentStatus.FAIL,
        method=EvaluationMethod.ANALYTICAL,
        summary="Fail run.",
    )
    cov_blocked = compute_coverage(resolved, [blocked_assessment])
    assert cov_blocked.blocked_count == 1
    cov_fail = compute_coverage(resolved, [fail_assessment])
    assert cov_fail.failed_count == 1

    # compute_coverage branches: UNDETERMINED resolved rule
    undetermined_resolved = ResolvedReviewRule(
        rule=r1,
        status=RuleApplicability.UNDETERMINED,
        rationale="Missing inputs",
        missing_inputs=["unknown_param"],
    )
    cov_undetermined = compute_coverage([undetermined_resolved], [])
    assert cov_undetermined.undetermined_count == 1

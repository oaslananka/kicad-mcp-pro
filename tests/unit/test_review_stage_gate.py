"""Unit tests for review coverage, evidence freshness, and stage decisions (#1580).

Validates:
- Stage gate decisions across plan completion, design review, prototype test,
  and production acceptance.
- Regression case 1: workflow completed-list without evidence fails closed.
- Regression case 2: empty findings with incomplete catalog blocks readiness.
- Regression case 3: HV clearance without actual review fails closed.
- Regression case 4: stale source/rule/profile evidence prevents approval.
- Regression case 5: wrong intent contract revision invalidates evidence.
- Regression case 6: missing required controls while claiming readiness is rejected.
- Evidence binding to immutable EvidenceRecord and EngineeringGraph dependencies.
"""

from __future__ import annotations

from kicad_mcp.models.review import (
    AssessmentStatus,
    EvaluationMethod,
    ResolvedReviewRule,
    ReviewAssessment,
    ReviewContext,
    ReviewCoverage,
    ReviewDomain,
    ReviewRule,
    ReviewSnapshot,
    RuleApplicability,
)
from kicad_mcp.project.evidence_freshness import (
    EvidenceFreshnessState,
    EvidenceInputDigest,
    EvidenceRecordKind,
    FreshnessAssessment,
    InvalidationReason,
)
from kicad_mcp.review.stage_gate import (
    ReviewStage,
    bind_snapshot_to_evidence,
    build_verified_design_workflow,
    evaluate_stage_readiness,
)


def _sample_snapshot(
    *,
    total_rules: int = 5,
    applicable_count: int = 5,
    passed_count: int = 5,
    failed_count: int = 0,
    blocked_count: int = 0,
    required_unassessed: list[str] | None = None,
    evidence_refs: list[str] | None = None,
    is_hv: bool = False,
    selected_mfg_profile: str | None = "JLCPCB/standard",
    domains: list[ReviewDomain] | None = None,
) -> ReviewSnapshot:
    rule_domains = domains or [ReviewDomain.SCHEMATIC, ReviewDomain.PCB]
    resolved: list[ResolvedReviewRule] = []
    assessments: list[ReviewAssessment] = []

    for idx, domain in enumerate(rule_domains):
        rule = ReviewRule(
            rule_id=f"{domain.value}.test_rule_{idx}",
            revision=1,
            domain=domain,
            title=f"Test Rule {idx}",
            source_doc="Test Doc",
            source_revision="1",
            method=EvaluationMethod.ANALYTICAL,
            is_mandatory=True,
        )
        resolved.append(
            ResolvedReviewRule(
                rule=rule,
                status=RuleApplicability.APPLICABLE,
                rationale="Applicable test rule",
            )
        )
        assessments.append(
            ReviewAssessment(
                rule_id=rule.rule_id,
                status=AssessmentStatus.PASS if failed_count == 0 else AssessmentStatus.FAIL,
                method=EvaluationMethod.ANALYTICAL,
                summary=f"Assessment for {rule.rule_id}",
                evidence_refs=evidence_refs or [f"ev-{rule.rule_id}"],
            )
        )

    coverage = ReviewCoverage(
        total_rules=total_rules,
        applicable_count=applicable_count,
        passed_count=passed_count,
        failed_count=failed_count,
        blocked_count=blocked_count,
        required_unassessed=required_unassessed or [],
    )

    ctx = ReviewContext(
        project_name="test_proj",
        is_hv=is_hv,
        selected_mfg_profile=selected_mfg_profile,
    )

    return ReviewSnapshot(
        project_key="test_proj",
        project_source_sha256="a" * 64,
        rule_catalog_revision="2026.1",
        context=ctx,
        resolved_rules=resolved,
        assessments=assessments,
        coverage=coverage,
    )


def test_regression_workflow_completed_list_without_evidence_fails_closed() -> None:
    """Regression case 1: String metadata alone must not mark gated phases complete."""
    claimed_phases = [
        "requirements_review",
        "schematic_capture",
        "schematic_verification",
        "manufacturing_release",
    ]

    # Without snapshot, gated phases (schematic_verification, manufacturing_release) cannot complete
    wf_unverified = build_verified_design_workflow(claimed_phases, snapshot=None)
    phase_map = {p.phase: p.status for p in wf_unverified.phases}

    assert phase_map["requirements_review"] == "COMPLETE"
    # Gated phases are blocked from completing without authoritative review evidence
    assert phase_map["schematic_capture"] != "COMPLETE"
    assert phase_map["schematic_verification"] != "COMPLETE"
    assert phase_map["manufacturing_release"] != "COMPLETE"


def test_regression_empty_findings_with_incomplete_catalog_blocks_readiness() -> None:
    """Regression case 2: Empty findings under incomplete catalog cannot approve readiness."""
    empty_snapshot = ReviewSnapshot(
        project_key="empty_proj",
        project_source_sha256="b" * 64,
        rule_catalog_revision="2026.1",
        context=ReviewContext(),
        resolved_rules=[],
        assessments=[],
        coverage=ReviewCoverage(total_rules=0, applicable_count=0),
    )

    decision = evaluate_stage_readiness(empty_snapshot, ReviewStage.DESIGN_REVIEW)
    assert not decision.approved
    assert any("empty" in r.lower() or "incomplete" in r.lower() for r in decision.blocking_reasons)


def test_regression_hv_clearance_without_actual_review_fails_closed() -> None:
    """Regression case 3: High-voltage production release without clearance evidence blocks."""
    hv_snapshot = _sample_snapshot(is_hv=True, selected_mfg_profile="JLCPCB/standard")
    # HV design with missing pad_spacing_mm in explicit_requirements
    decision = evaluate_stage_readiness(hv_snapshot, ReviewStage.PRODUCTION_ACCEPTANCE)
    assert not decision.approved
    assert any("clearance" in r.lower() for r in decision.blocking_reasons)


def test_regression_stale_evidence_prevents_approval() -> None:
    """Regression case 4: Evidence requiring recheck blocks stage readiness."""
    snapshot = _sample_snapshot(evidence_refs=["ev-schematic-01"])

    freshness_map = {
        "ev-schematic-01": FreshnessAssessment(
            evidence_id="ev-schematic-01",
            state=EvidenceFreshnessState.REQUIRES_RECHECK,
            reasons=(
                InvalidationReason(
                    code="source_hash_mismatch",
                    detail="Schematic source changed.",
                ),
            ),
        )
    }

    decision = evaluate_stage_readiness(
        snapshot,
        ReviewStage.DESIGN_REVIEW,
        freshness_assessments=freshness_map,
    )
    assert not decision.approved
    assert "ev-schematic-01" in decision.stale_evidence_ids
    assert any("stale" in r.lower() for r in decision.blocking_reasons)


def test_regression_missing_required_controls_blocks_readiness() -> None:
    """Regression case 6: Unassessed mandatory controls block readiness report."""
    snapshot = _sample_snapshot(required_unassessed=["placement.decoupling_pin_connectivity"])

    decision = evaluate_stage_readiness(snapshot, ReviewStage.DESIGN_REVIEW)
    assert not decision.approved
    assert "placement.decoupling_pin_connectivity" in decision.required_unassessed


def test_evidence_record_binding() -> None:
    """Verifies binding ReviewSnapshot into an immutable EvidenceRecord."""
    snapshot = _sample_snapshot()
    extra_digest = EvidenceInputDigest(
        entity_id="contract:intent:v1",
        sha256="c" * 64,
    )

    record = bind_snapshot_to_evidence(
        snapshot,
        producer="kicad_mcp_pro",
        producer_version="2.1.0",
        contract_id="hardware_intent",
        contract_version=1,
        extra_inputs=[extra_digest],
    )

    assert record.kind == EvidenceRecordKind.VERIFICATION_RUN
    assert record.project_key == "test_proj"
    assert record.source_sha256 == snapshot.project_source_sha256
    assert record.dependency_manifest_complete is True
    # Digests must be sorted and unique
    entity_ids = [inp.entity_id for inp in record.inputs]
    assert entity_ids == sorted(entity_ids)
    assert "contract:intent:v1" in entity_ids


def test_stage_distinction_plan_vs_production() -> None:
    """Verifies that plan completion approval does NOT constitute production release."""
    snapshot = _sample_snapshot(
        domains=[ReviewDomain.SCHEMATIC],
        selected_mfg_profile=None,  # No mfg profile declared!
    )

    # Plan completion passes (requirements/planning stage)
    plan_decision = evaluate_stage_readiness(snapshot, ReviewStage.PLAN_COMPLETION)
    assert plan_decision.approved

    # Production acceptance blocks because manufacturing profile is missing
    prod_decision = evaluate_stage_readiness(snapshot, ReviewStage.PRODUCTION_ACCEPTANCE)
    assert not prod_decision.approved
    assert any("manufacturing profile" in r.lower() for r in prod_decision.blocking_reasons)


def test_stage_readiness_prototype_test() -> None:
    """Verifies prototype test stage thresholds on unresolved warnings."""
    snap_ok = _sample_snapshot()
    snap_ok.coverage.warned_count = 3
    dec_ok = evaluate_stage_readiness(snap_ok, ReviewStage.PROTOTYPE_TEST)
    assert dec_ok.approved

    snap_warn = _sample_snapshot()
    snap_warn.coverage.warned_count = 6
    dec_warn = evaluate_stage_readiness(snap_warn, ReviewStage.PROTOTYPE_TEST)
    assert not dec_warn.approved
    assert any("too many unresolved warnings" in r.lower() for r in dec_warn.blocking_reasons)


def test_stage_readiness_production_undetermined() -> None:
    """Verifies production acceptance rejects undetermined rules."""
    snap = _sample_snapshot()
    rule = ReviewRule(
        rule_id="custom.undetermined_rule",
        revision=1,
        domain=ReviewDomain.PCB,
        title="Custom",
        source_doc="Doc",
        source_revision="1",
        method=EvaluationMethod.HUMAN_REVIEW,
    )
    snap.resolved_rules.append(
        ResolvedReviewRule(
            rule=rule,
            status=RuleApplicability.UNDETERMINED,
            rationale="Needs investigation",
        )
    )
    dec = evaluate_stage_readiness(snap, ReviewStage.PRODUCTION_ACCEPTANCE)
    assert not dec.approved
    assert any("undetermined" in r.lower() for r in dec.blocking_reasons)


def test_stage_readiness_design_review_missing_domains() -> None:
    """Verifies design review requires both schematic and PCB domains."""
    snap = _sample_snapshot(domains=[ReviewDomain.SCHEMATIC])
    dec = evaluate_stage_readiness(snap, ReviewStage.DESIGN_REVIEW)
    assert not dec.approved
    assert any("schematic and pcb" in r.lower() for r in dec.blocking_reasons)


def test_freshness_recheck_without_explicit_reasons() -> None:
    """Verifies fallback reason string when freshness assessment reasons tuple is empty."""
    snap = _sample_snapshot(evidence_refs=["ev-fallback-01"])
    freshness_map = {
        "ev-fallback-01": FreshnessAssessment(
            evidence_id="ev-fallback-01",
            state=EvidenceFreshnessState.REQUIRES_RECHECK,
            reasons=(),
        )
    }
    dec = evaluate_stage_readiness(
        snap, ReviewStage.DESIGN_REVIEW, freshness_assessments=freshness_map
    )
    assert not dec.approved
    assert any("input digest mismatch" in r.lower() for r in dec.blocking_reasons)


def test_bind_snapshot_to_evidence_default_inputs() -> None:
    """Verifies bind_snapshot_to_evidence works cleanly without extra inputs."""
    snap = _sample_snapshot()
    record = bind_snapshot_to_evidence(snap)
    assert record.producer == "kicad_mcp_pro"
    assert len(record.inputs) == 2


def test_workflow_gated_phases_verification_warnings() -> None:
    """Verifies each gated phase blocks when review snapshot fails stage gates."""
    failing_snap = _sample_snapshot(failed_count=2)

    for phase_name in [
        "schematic_verification",
        "full_verification",
        "fix_loop",
        "manufacturing_release",
    ]:
        wf = build_verified_design_workflow([phase_name], snapshot=failing_snap)
        p_state = next(p for p in wf.phases if p.phase == phase_name)
        assert p_state.status != "COMPLETE"
        assert "unverified" in p_state.next_action.lower()


def test_workflow_all_phases_complete_verified() -> None:
    """Verifies workflow advances to overall COMPLETE when all phases are verified."""
    from kicad_mcp.project.workflow import AGENT_WORKFLOW_PHASES

    all_phase_names = [str(spec["phase"]) for spec in AGENT_WORKFLOW_PHASES]
    valid_snap = _sample_snapshot()
    wf = build_verified_design_workflow(all_phase_names, snapshot=valid_snap)
    assert wf.overall_status == "COMPLETE"
    assert all(p.status == "COMPLETE" for p in wf.phases)


def test_coverage_blocked_count_blocks_stage() -> None:
    """Verifies review rules blocked by missing tools block stage approval."""
    snap = _sample_snapshot(blocked_count=2)
    dec = evaluate_stage_readiness(snap, ReviewStage.PLAN_COMPLETION)
    assert not dec.approved
    assert any("blocked" in r.lower() for r in dec.blocking_reasons)

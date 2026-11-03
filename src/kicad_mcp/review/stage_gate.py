"""Stage gate decisions and evidence freshness binding for engineering review (#1580).

In accordance with milestone M18 principles:
- Distinguishes plan completion, design review, prototype test, and production acceptance.
- Stale, unassessed, or blocked evidence prevents stage readiness approval.
- Completed metadata alone never becomes engineering approval.
- Binds ReviewSnapshot to immutable EvidenceRecord and EngineeringGraph dependencies.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from enum import StrEnum
from typing import Any, cast

from pydantic import BaseModel, ConfigDict, Field

from ..models.review import (
    ReviewDomain,
    ReviewSnapshot,
    RuleApplicability,
)
from ..models.state import (
    DesignWorkflowState,
    WorkflowPhaseState,
    WorkflowPhaseStatus,
    WorkflowRole,
)
from ..project.evidence_freshness import (
    EvidenceFreshnessState,
    EvidenceInputDigest,
    EvidenceRecord,
    EvidenceRecordKind,
    FreshnessAssessment,
)
from ..project.workflow import AGENT_WORKFLOW_PHASES


class ReviewStage(StrEnum):
    """Lifecycle stages for engineering review decisions."""

    PLAN_COMPLETION = "plan_completion"
    DESIGN_REVIEW = "design_review"
    PROTOTYPE_TEST = "prototype_test"
    PRODUCTION_ACCEPTANCE = "production_acceptance"


class StageGateDecision(BaseModel):
    """Outcome of evaluating review readiness for a specific engineering stage."""

    model_config = ConfigDict(extra="forbid")

    stage: ReviewStage
    approved: bool
    summary: str
    blocking_reasons: list[str] = Field(default_factory=list)
    stale_evidence_ids: list[str] = Field(default_factory=list)
    required_unassessed: list[str] = Field(default_factory=list)
    undetermined_rules: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


def _check_freshness_blockers(
    snapshot: ReviewSnapshot,
    freshness_assessments: Mapping[str, FreshnessAssessment] | None,
) -> tuple[list[str], list[str]]:
    blocking: list[str] = []
    stale_ids: list[str] = []
    if not freshness_assessments:
        return blocking, stale_ids

    for assessment in snapshot.assessments:
        for ev_ref in assessment.evidence_refs:
            f_assessment = freshness_assessments.get(ev_ref)
            if not f_assessment or f_assessment.state == EvidenceFreshnessState.STILL_VALID:
                continue
            stale_ids.append(ev_ref)
            reason_desc = (
                ", ".join(r.code for r in f_assessment.reasons)
                if f_assessment.reasons
                else "input digest mismatch"
            )
            blocking.append(
                f"Evidence '{ev_ref}' for rule '{assessment.rule_id}' is stale "
                f"({f_assessment.state.value}): {reason_desc}."
            )
    return blocking, stale_ids


def _check_coverage_blockers(snapshot: ReviewSnapshot) -> list[str]:
    blocking: list[str] = []
    if snapshot.coverage.required_unassessed:
        for rule_id in snapshot.coverage.required_unassessed:
            blocking.append(f"Required mandatory rule '{rule_id}' has not been assessed.")
    if snapshot.coverage.failed_count > 0:
        blocking.append(f"{snapshot.coverage.failed_count} review rule(s) failed.")
    if snapshot.coverage.blocked_count > 0:
        blocking.append(
            f"{snapshot.coverage.blocked_count} review rule(s) blocked by missing tools or runtime."
        )
    if snapshot.coverage.total_rules == 0:
        blocking.append("Rule catalog is empty; cannot evaluate engineering readiness.")
    return blocking


def _check_production_blockers(
    snapshot: ReviewSnapshot,
    undetermined: Sequence[str],
    blocking: list[str],
) -> None:
    if undetermined:
        blocking.append(
            f"Production release does not permit undetermined rules: {', '.join(undetermined)}."
        )
    if not snapshot.context.selected_mfg_profile:
        blocking.append("Production release requires a declared, versioned manufacturing profile.")
    if snapshot.context.is_hv and not snapshot.context.explicit_requirements.get("pad_spacing_mm"):
        blocking.append("Production release for HV design requires physical clearance.")


def _check_stage_blockers(
    snapshot: ReviewSnapshot,
    stage: ReviewStage,
    undetermined: Sequence[str],
) -> tuple[str, list[str]]:
    blocking: list[str] = []
    if stage == ReviewStage.PLAN_COMPLETION:
        return "Plan completion review", blocking
    if stage == ReviewStage.DESIGN_REVIEW:
        assessed_domains = {r.rule.domain for r in snapshot.resolved_rules}
        if (
            ReviewDomain.SCHEMATIC not in assessed_domains
            or ReviewDomain.PCB not in assessed_domains
        ):
            blocking.append(
                "Design review requires rule evaluation for both schematic and PCB domains."
            )
        return "Design review", blocking
    if stage == ReviewStage.PROTOTYPE_TEST:
        if snapshot.coverage.warned_count > 5:
            blocking.append(
                f"Too many unresolved warnings ({snapshot.coverage.warned_count}) for prototype."
            )
        return "Prototype test stage", blocking
    if stage == ReviewStage.PRODUCTION_ACCEPTANCE:
        _check_production_blockers(snapshot, undetermined, blocking)
        return "Production manufacturing acceptance", blocking
    return f"Stage {stage.value}", blocking


def evaluate_stage_readiness(
    snapshot: ReviewSnapshot,
    stage: ReviewStage,
    *,
    freshness_assessments: Mapping[str, FreshnessAssessment] | None = None,
) -> StageGateDecision:
    """Evaluate whether a ReviewSnapshot satisfies the criteria for an engineering stage."""
    fresh_blockers, stale_ids = _check_freshness_blockers(snapshot, freshness_assessments)
    cov_blockers = _check_coverage_blockers(snapshot)

    undetermined = [
        r.rule.rule_id
        for r in snapshot.resolved_rules
        if r.status == RuleApplicability.UNDETERMINED
    ]

    summary_base, stage_blockers = _check_stage_blockers(snapshot, stage, undetermined)
    blocking = fresh_blockers + cov_blockers + stage_blockers

    approved = len(blocking) == 0
    if approved:
        summary = f"{summary_base}: APPROVED. All applicable checks verified with fresh evidence."
    else:
        summary = f"{summary_base}: BLOCKED ({len(blocking)} issue(s) require remediation)."

    return StageGateDecision(
        stage=stage,
        approved=approved,
        summary=summary,
        blocking_reasons=blocking,
        stale_evidence_ids=sorted(set(stale_ids)),
        required_unassessed=list(snapshot.coverage.required_unassessed),
        undetermined_rules=undetermined,
        metadata={"stage": stage.value, "approved": approved},
    )


def bind_snapshot_to_evidence(
    snapshot: ReviewSnapshot,
    *,
    producer: str = "kicad_mcp_pro",
    producer_version: str = "1.0.0",
    contract_id: str | None = None,
    contract_version: int | None = None,
    extra_inputs: Sequence[EvidenceInputDigest] | None = None,
) -> EvidenceRecord:
    """Bind a verified ReviewSnapshot into an immutable EvidenceRecord."""
    source_digest = EvidenceInputDigest(
        entity_id=f"project:{snapshot.project_key}:source",
        sha256=snapshot.project_source_sha256,
    )
    catalog_sha256 = hashlib.sha256(snapshot.rule_catalog_revision.encode("utf-8")).hexdigest()
    catalog_digest = EvidenceInputDigest(
        entity_id=f"catalog:{snapshot.rule_catalog_revision}",
        sha256=catalog_sha256,
    )

    all_inputs_map: dict[str, EvidenceInputDigest] = {
        source_digest.entity_id: source_digest,
        catalog_digest.entity_id: catalog_digest,
    }
    if extra_inputs:
        for entry in extra_inputs:
            all_inputs_map[entry.entity_id] = entry

    sorted_inputs = tuple(all_inputs_map[k] for k in sorted(all_inputs_map.keys()))

    evidence_id = (
        f"review-{snapshot.project_key[:16]}-{snapshot.project_source_sha256[:12]}-"
        f"{catalog_sha256[:8]}"
    )

    return EvidenceRecord(
        schema_version=1,
        evidence_id=evidence_id,
        kind=EvidenceRecordKind.VERIFICATION_RUN,
        project_key=snapshot.project_key,
        source_revision=snapshot.rule_catalog_revision,
        source_sha256=snapshot.project_source_sha256,
        producer=producer,
        producer_version=producer_version,
        captured_at=snapshot.created_at,
        dependency_manifest_complete=True,
        inputs=sorted_inputs,
        contract_id=contract_id,
        contract_version=contract_version,
        provenance_source="engineering_review_snapshot_v1",
    )


def _verify_phase_readiness(
    name: str,
    snapshot: ReviewSnapshot | None,
    freshness_assessments: Mapping[str, FreshnessAssessment] | None,
) -> tuple[bool, str]:
    if snapshot is None:
        return False, f"Phase '{name}' claimed complete without review snapshot."

    stage_map = {
        "schematic_verification": (ReviewStage.DESIGN_REVIEW, "Schematic verification unverified"),
        "full_verification": (ReviewStage.DESIGN_REVIEW, "Verification unverified"),
        "fix_loop": (ReviewStage.DESIGN_REVIEW, "Verification unverified"),
        "manufacturing_release": (ReviewStage.PRODUCTION_ACCEPTANCE, "Release unverified"),
    }
    stage_spec = stage_map.get(name)
    if not stage_spec:
        return True, ""

    stage, prefix = stage_spec
    decision = evaluate_stage_readiness(
        snapshot,
        stage,
        freshness_assessments=freshness_assessments,
    )
    if decision.approved:
        return True, ""

    reasons_str = "; ".join(decision.blocking_reasons[:2])
    return False, f"{prefix}: {reasons_str}"


def _evaluate_phase_item(
    spec: Mapping[str, Any],
    claimed_complete: bool,
    snapshot: ReviewSnapshot | None,
    freshness_assessments: Mapping[str, FreshnessAssessment] | None,
    current_index: int | None,
    index: int,
) -> tuple[WorkflowPhaseState, int | None]:
    name = str(spec["phase"])
    gates = list(cast(list[str], spec.get("gates") or []))
    role = cast(WorkflowRole, spec["role"])

    is_verified = True
    warning = ""
    if claimed_complete and gates:
        is_verified, warning = _verify_phase_readiness(name, snapshot, freshness_assessments)

    if claimed_complete and is_verified:
        status: WorkflowPhaseStatus = "COMPLETE"
    elif current_index is None:
        status = "READY"
        current_index = index
    else:
        status = "PENDING"

    next_act = warning if warning else str(spec["next_action"])
    phase_state = WorkflowPhaseState(
        phase=name,
        role=role,
        status=status,
        high_level_tool=str(spec["high_level_tool"]),
        next_action=next_act,
        gates=gates,
        human_gate_required=role == "Release Manager",
    )
    return phase_state, current_index


def build_verified_design_workflow(
    completed_phases: list[str],
    snapshot: ReviewSnapshot | None = None,
    *,
    freshness_assessments: Mapping[str, FreshnessAssessment] | None = None,
) -> DesignWorkflowState:
    """Build the design workflow state where gated phases require verified evidence.

    Phases with quality gates cannot advance to COMPLETE on string metadata alone.
    """
    completed = {name.strip() for name in completed_phases if name.strip()}
    phases: list[WorkflowPhaseState] = []
    current_index: int | None = None

    for index, spec in enumerate(AGENT_WORKFLOW_PHASES):
        name = str(spec["phase"])
        phase_state, current_index = _evaluate_phase_item(
            spec,
            name in completed,
            snapshot,
            freshness_assessments,
            current_index,
            index,
        )
        phases.append(phase_state)

    if current_index is None:
        current = phases[-1]
        return DesignWorkflowState(
            current_phase=current.phase,
            current_role=current.role,
            overall_status="COMPLETE",
            phases=phases,
            next_action="All phases verified with fresh evidence — ready for release.",
            human_gate_required=False,
        )

    current = phases[current_index]
    return DesignWorkflowState(
        current_phase=current.phase,
        current_role=current.role,
        overall_status="READY",
        phases=phases,
        next_action=current.next_action,
        human_gate_required=current.human_gate_required,
    )

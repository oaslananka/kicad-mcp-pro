"""Unified engineering review reporting and prioritized action synthesis (#1587).

Exposes a consistent review snapshot through structured and Markdown surfaces:
- Groups findings into 5 distinct prioritized action categories:
  1. Critical Defects (mandatory electrical, physical, mechanical, manufacturing violations)
  2. Missing Evidence (unassessed/blocked mandatory checks, unprovided profiles)
  3. External & Physical Review (simulation reports, bring-up measurements, HV signoffs)
  4. Advisory Recommendations (derating ROC margins, NRND parts, offline stock snapshots)
  5. Cosmetic Findings (orthogonal routing corners, visual wire alignment)
- Guarantees 100% agreement between structured JSON and human-readable Markdown.
- Evaluates stage-gate readiness honestly without allowing missing inputs to pass.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from ..models.review import (
    AssessmentStatus,
    EvaluationMethod,
    ReviewCoverage,
    ReviewDomain,
    ReviewSnapshot,
    RuleApplicability,
)
from .catalog import compute_coverage
from .stage_gate import ReviewStage, StageGateDecision


class ReviewActionCategory(StrEnum):
    """Categorical classification of review findings and gaps."""

    CRITICAL_DEFECT = "CRITICAL_DEFECT"
    MISSING_EVIDENCE = "MISSING_EVIDENCE"
    EXTERNAL_PHYSICAL_REVIEW = "EXTERNAL_PHYSICAL_REVIEW"
    ADVISORY_RECOMMENDATION = "ADVISORY_RECOMMENDATION"
    COSMETIC_FINDING = "COSMETIC_FINDING"


class PrioritizedActionItem(BaseModel):
    """Actionable finding or gap in engineering review."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    priority: int = Field(ge=1, le=5)
    category: ReviewActionCategory
    rule_id: str
    title: str
    object_ref: str = ""
    description: str
    remediation: str
    is_blocking: bool


class UnifiedReviewReport(BaseModel):
    """Integrated review report payload with synchronized structured and text output."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    project_name: str
    project_source_sha256: str
    stage: ReviewStage
    is_ready_for_stage: bool
    verdict: Literal["PASS", "WARN", "FAIL", "BLOCKED", "NOT_ASSESSED"]
    summary: str
    coverage: ReviewCoverage
    actions: list[PrioritizedActionItem] = Field(default_factory=list)
    critical_defects_count: int = 0
    missing_evidence_count: int = 0
    external_physical_review_count: int = 0
    advisory_recommendations_count: int = 0
    cosmetic_findings_count: int = 0
    markdown_text: str = ""


def _classify_finding_category(
    rule_id: str,
    domain: ReviewDomain,
    method: EvaluationMethod,
    severity: str,
) -> tuple[ReviewActionCategory, int, bool]:
    """Map finding to one of five prioritized review categories."""
    # 1. Cosmetic findings
    if (
        domain == ReviewDomain.ROUTING
        and "orthogonal" in rule_id
        or domain in (ReviewDomain.SCHEMATIC, ReviewDomain.PCB)
        and "cosmetics" in rule_id
    ):
        return ReviewActionCategory.COSMETIC_FINDING, 5, False

    # 2. External simulation, physical measurement, or specialist signoff
    if (
        method == EvaluationMethod.PHYSICAL_MEASUREMENT
        or "external_simulation" in rule_id
        or "specialist_safety" in rule_id
        or "bringup" in rule_id
    ):
        is_blocking = severity == "error"
        return ReviewActionCategory.EXTERNAL_PHYSICAL_REVIEW, 3, is_blocking

    # 3. Critical defects
    if severity == "error":
        return ReviewActionCategory.CRITICAL_DEFECT, 1, True

    # 4. Advisory recommendations (warnings)
    return ReviewActionCategory.ADVISORY_RECOMMENDATION, 4, False


def _unassessed_mandatory_rule_actions(
    snapshot: ReviewSnapshot,
) -> list[PrioritizedActionItem]:
    """Mandatory unresolved or absent assessments block a truthful PASS verdict."""
    if not snapshot.resolved_rules:
        return [
            PrioritizedActionItem(
                priority=2,
                category=ReviewActionCategory.MISSING_EVIDENCE,
                rule_id="catalog.empty",
                title="Missing Evidence: Engineering rule catalog",
                description="No registered engineering review rules were evaluated.",
                remediation="Load the versioned review catalog and run applicable checks.",
                is_blocking=True,
            )
        ]

    assessed_ids = {assessment.rule_id for assessment in snapshot.assessments}
    actions = []
    for resolved in snapshot.resolved_rules:
        rule = resolved.rule
        if (
            not rule.is_mandatory
            or rule.rule_id in assessed_ids
            or resolved.status
            not in {
                RuleApplicability.APPLICABLE,
                RuleApplicability.UNDETERMINED,
            }
        ):
            continue
        missing = resolved.missing_inputs or rule.required_inputs
        actions.append(
            PrioritizedActionItem(
                priority=2,
                category=ReviewActionCategory.MISSING_EVIDENCE,
                rule_id=rule.rule_id,
                title=f"Missing Evidence: {rule.title}",
                description=(
                    f"Mandatory review {rule.rule_id} has no assessment; "
                    f"missing inputs: {', '.join(missing) or 'review execution'}."
                ),
                remediation=rule.remediation or "Execute the mandatory review with current inputs.",
                is_blocking=True,
            )
        )
    return actions


def _stage_gate_blockers(
    stage_decision: StageGateDecision | None,
) -> list[PrioritizedActionItem]:
    """Never render a denied stage-gate authorization as engineering PASS."""
    if stage_decision is None or stage_decision.approved:
        return []
    explanation = "; ".join(stage_decision.blocking_reasons) or stage_decision.summary
    return [
        PrioritizedActionItem(
            priority=2,
            category=ReviewActionCategory.MISSING_EVIDENCE,
            rule_id="stage.authorization",
            title="Stage authorization blocked",
            description=explanation,
            remediation="Resolve the stage-gate blocking reasons and obtain approval.",
            is_blocking=True,
        )
    ]


def _is_report_ready(
    actions: list[PrioritizedActionItem],
    stage_decision: StageGateDecision | None,
) -> bool:
    """Stage readiness requires no blocking actions and appropriate approval."""
    return not any(item.is_blocking for item in actions) and (
        stage_decision is None or stage_decision.approved
    )


def _resolve_report_coverage(
    snapshot: ReviewSnapshot,
    coverage: ReviewCoverage | None,
) -> ReviewCoverage:
    if coverage is not None:
        return coverage
    return compute_coverage(snapshot.resolved_rules, snapshot.assessments)


def generate_unified_review_report(
    snapshot: ReviewSnapshot,
    coverage: ReviewCoverage | None = None,
    stage: ReviewStage = ReviewStage.DESIGN_REVIEW,
    stage_decision: StageGateDecision | None = None,
) -> UnifiedReviewReport:
    """Synthesize complete engineering review snapshot into unified prioritized report."""
    coverage = _resolve_report_coverage(snapshot, coverage)

    rule_map = {r.rule.rule_id: r.rule for r in snapshot.resolved_rules}
    actions: list[PrioritizedActionItem] = _unassessed_mandatory_rule_actions(snapshot)
    actions.extend(_stage_gate_blockers(stage_decision))

    # 1. Collect missing evidence items
    for assessment in snapshot.assessments:
        rule = rule_map.get(assessment.rule_id)
        is_mandatory = rule.is_mandatory if rule else True
        rule_title = rule.title if rule else assessment.rule_id

        if assessment.status in {AssessmentStatus.NOT_ASSESSED, AssessmentStatus.BLOCKED}:
            missing_text = (
                ", ".join(assessment.missing_inputs)
                if assessment.missing_inputs
                else "required input data"
            )
            actions.append(
                PrioritizedActionItem(
                    priority=2,
                    category=ReviewActionCategory.MISSING_EVIDENCE,
                    rule_id=assessment.rule_id,
                    title=f"Missing Evidence: {rule_title}",
                    object_ref="",
                    description=(
                        f"Rule {assessment.rule_id} status is {assessment.status}. "
                        f"Missing inputs: {missing_text}. Summary: {assessment.summary}"
                    ),
                    remediation=(
                        rule.remediation
                        if rule and rule.remediation
                        else f"Provide {missing_text} and re-run review."
                    ),
                    is_blocking=is_mandatory,
                )
            )

        # 2. Collect findings from assessed rules
        for finding in assessment.findings:
            domain = rule.domain if rule else ReviewDomain.PCB
            method = rule.method if rule else assessment.method
            cat, priority, is_blocking = _classify_finding_category(
                rule_id=assessment.rule_id,
                domain=domain,
                method=method,
                severity=finding.severity,
            )
            actions.append(
                PrioritizedActionItem(
                    priority=priority,
                    category=cat,
                    rule_id=assessment.rule_id,
                    title=rule_title,
                    object_ref=finding.object_ref,
                    description=finding.description,
                    remediation=finding.remediation or (rule.remediation if rule else ""),
                    is_blocking=is_blocking,
                )
            )

    # Sort actions by priority (1 to 5), then rule_id
    actions.sort(key=lambda a: (a.priority, a.rule_id))

    crit_count = sum(1 for a in actions if a.category == ReviewActionCategory.CRITICAL_DEFECT)
    missing_count = sum(1 for a in actions if a.category == ReviewActionCategory.MISSING_EVIDENCE)
    ext_count = sum(
        1 for a in actions if a.category == ReviewActionCategory.EXTERNAL_PHYSICAL_REVIEW
    )
    adv_count = sum(
        1 for a in actions if a.category == ReviewActionCategory.ADVISORY_RECOMMENDATION
    )
    cosm_count = sum(1 for a in actions if a.category == ReviewActionCategory.COSMETIC_FINDING)

    # Verdict & readiness; an external approval cannot waive internal blockers.
    is_ready = _is_report_ready(actions, stage_decision)

    if any(a.is_blocking for a in actions if a.category == ReviewActionCategory.MISSING_EVIDENCE):
        verdict = "BLOCKED"
        headline = f"Review blocked: {missing_count} required input/evidence item(s) unassessed."
    elif crit_count > 0:
        verdict = "FAIL"
        headline = f"Review failed: {crit_count} critical engineering defect(s) detected."
    elif any(
        a.is_blocking
        for a in actions
        if a.category == ReviewActionCategory.EXTERNAL_PHYSICAL_REVIEW
    ):
        verdict = "FAIL"
        headline = "Review failed: external solver or bring-up verification violation."
    elif adv_count > 0 or ext_count > 0 or cosm_count > 0:
        verdict = "WARN"
        headline = (
            f"Review passed with advisory notes ({adv_count} advisory, {cosm_count} cosmetic)."
        )
    else:
        verdict = "PASS"
        headline = "Review passed: all applicable engineering rules satisfied."

    ready_str = "YES" if is_ready else "NO"
    # Build Markdown
    lines = [
        f"# Engineering Review Report — {snapshot.context.project_name or 'Active Project'}",
        "",
        (
            f"**Review Stage:** `{stage.value}` | "
            f"**Verdict:** `{verdict}` | **Ready for Stage:** `{ready_str}`"
        ),
        f"**Source Revision SHA256:** `{snapshot.context.project_source_sha256 or 'unversioned'}`",
        "",
        f"> {headline}",
        "",
        "## Review Coverage & Evidence Metrics",
        "",
        "| Metric | Count |",
        "|--------|-------|",
        f"| Total Rules Registered | {coverage.total_rules} |",
        f"| Applicable Rules | {coverage.applicable_count} |",
        f"| Passed Rules | {coverage.passed_count} |",
        f"| Warned Rules | {coverage.warned_count} |",
        f"| Failed Rules | {coverage.failed_count} |",
        f"| Blocked Rules | {coverage.blocked_count} |",
        f"| Not Assessed Rules | {coverage.not_assessed_count} |",
        "",
    ]

    # Sections for each category
    def append_section(title: str, cat: ReviewActionCategory) -> None:
        cat_actions = [a for a in actions if a.category == cat]
        if not cat_actions:
            return
        lines.append(f"## {title} ({len(cat_actions)})")
        lines.append("")
        for idx, act in enumerate(cat_actions, start=1):
            block_tag = " **[BLOCKING]**" if act.is_blocking else ""
            ref_tag = f" (`{act.object_ref}`)" if act.object_ref else ""
            lines.append(f"### {idx}. {act.title}{ref_tag}{block_tag}")
            lines.append(f"- **Rule ID:** `{act.rule_id}`")
            lines.append(f"- **Finding:** {act.description}")
            if act.remediation:
                lines.append(f"- **Remediation:** {act.remediation}")
            lines.append("")

    append_section("1. Critical Engineering Defects", ReviewActionCategory.CRITICAL_DEFECT)
    append_section("2. Missing Evidence & Unassessed Inputs", ReviewActionCategory.MISSING_EVIDENCE)
    append_section(
        "3. External Simulation & Physical Lab Verification",
        ReviewActionCategory.EXTERNAL_PHYSICAL_REVIEW,
    )
    append_section("4. Advisory Recommendations", ReviewActionCategory.ADVISORY_RECOMMENDATION)
    append_section("5. Cosmetic & Presentation Preferences", ReviewActionCategory.COSMETIC_FINDING)

    # Next step recommendation
    lines.append("## Next Action Recommendation")
    lines.append("")
    if verdict in ("FAIL", "BLOCKED"):
        first_blocker = next((a for a in actions if a.is_blocking), None)
        if first_blocker:
            lines.append(
                f"Address blocking item: **{first_blocker.title}** (`{first_blocker.rule_id}`)."
            )
            lines.append(f"Remediation: {first_blocker.remediation}")
        else:
            lines.append("Resolve blocking issues and re-run review.")
    elif verdict == "WARN":
        lines.append(
            "Review advisory recommendations. If acceptable, "
            "proceed to next stage or prototype testing."
        )
    else:
        lines.append(
            f"All stage checks passed. Project is ready for stage `{stage.value}` signoff."
        )

    md_text = "\n".join(lines)

    return UnifiedReviewReport(
        project_name=snapshot.context.project_name,
        project_source_sha256=snapshot.context.project_source_sha256,
        stage=stage,
        is_ready_for_stage=is_ready,
        verdict=verdict,
        summary=headline,
        coverage=coverage,
        actions=actions,
        critical_defects_count=crit_count,
        missing_evidence_count=missing_count,
        external_physical_review_count=ext_count,
        advisory_recommendations_count=adv_count,
        cosmetic_findings_count=cosm_count,
        markdown_text=md_text,
    )

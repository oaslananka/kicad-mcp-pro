"""Narrow adapter between ReviewAssessment/ReviewSnapshot and VerdictReport (verdict.v1) (#1579).

In accordance with milestone M18 principles:
- Required NOT_ASSESSED or BLOCKED statuses NEVER adapt to PASS.
- Public verdict.v1 literals ("PASS", "WARN", "FAIL") and envelope fields are preserved.
- Rich versioned review metadata is attached to metadata without breaking legacy clients.
"""

from __future__ import annotations

from typing import Any

from ..models.review import (
    AssessmentStatus,
    ReviewAssessment,
    ReviewFinding,
    ReviewRule,
    ReviewSnapshot,
)
from ..models.verdict import Finding, Verdict, VerdictReport, stable_finding_id


def adapt_finding(finding: ReviewFinding) -> Finding:
    """Convert pure-domain ReviewFinding to legacy verdict.v1 Finding."""
    loc = finding.object_ref
    if finding.pin:
        loc = f"{loc}.{finding.pin}" if loc else finding.pin
    if finding.location_mm:
        x_mm, y_mm = finding.location_mm
        loc_coord = f"({x_mm:.3f}, {y_mm:.3f}) mm"
        loc = f"{loc} @ {loc_coord}" if loc else loc_coord

    metadata: dict[str, Any] = {
        "rule_id": finding.rule_id,
        "rule_revision": finding.rule_revision,
    }
    if finding.net:
        metadata["net"] = finding.net
    if finding.layer:
        metadata["layer"] = finding.layer
    if finding.measured_value is not None:
        metadata["measured_value"] = finding.measured_value
    if finding.expected_value is not None:
        metadata["expected_value"] = finding.expected_value
    if finding.units:
        metadata["units"] = finding.units

    return Finding(
        id=finding.id,
        severity=finding.severity,
        location=loc,
        description=finding.description,
        evidence=[{"ref": ref} for ref in finding.evidence_refs],
        remediation=finding.remediation,
        retryable=False,
        failure_mode="design",
        metadata=metadata,
    )


def adapt_assessment_to_verdict(
    assessment: ReviewAssessment,
    rule: ReviewRule | None = None,
) -> VerdictReport:
    """Adapt a single ReviewAssessment to a legacy VerdictReport.

    Critical invariant:
    - NOT_ASSESSED and BLOCKED must NEVER adapt to verdict='PASS'.
    """
    is_mandatory = rule.is_mandatory if rule is not None else True
    legacy_findings = [adapt_finding(f) for f in assessment.findings]

    metadata: dict[str, Any] = {
        "review_status": assessment.status.value,
        "rule_id": assessment.rule_id,
        "rule_revision": assessment.rule_revision,
        "evaluation_method": assessment.method.value,
        **assessment.metadata,
    }
    if assessment.missing_inputs:
        metadata["missing_inputs"] = assessment.missing_inputs

    if assessment.status == AssessmentStatus.PASS:
        return VerdictReport(
            verdict="PASS",
            severity="info",
            failure_mode="none",
            summary=assessment.summary,
            text=f"PASS: {assessment.summary}",
            findings=[],
            evidence=[{"ref": ref} for ref in assessment.evidence_refs],
            metadata=metadata,
        )

    if assessment.status == AssessmentStatus.NOT_APPLICABLE:
        return VerdictReport(
            verdict="PASS",
            severity="info",
            failure_mode="none",
            summary=f"[NOT APPLICABLE] {assessment.summary}",
            text=f"NOT APPLICABLE: {assessment.summary}",
            findings=[],
            evidence=[{"ref": ref} for ref in assessment.evidence_refs],
            metadata=metadata,
        )

    if assessment.status == AssessmentStatus.WARN:
        return VerdictReport(
            verdict="WARN",
            severity="warning",
            failure_mode="design",
            summary=assessment.summary,
            text=f"WARN: {assessment.summary}",
            findings=legacy_findings,
            evidence=[{"ref": ref} for ref in assessment.evidence_refs],
            remediation=legacy_findings[0].remediation if legacy_findings else "",
            metadata=metadata,
        )

    if assessment.status == AssessmentStatus.FAIL:
        return VerdictReport(
            verdict="FAIL",
            severity="error",
            failure_mode="design",
            summary=assessment.summary,
            text=f"FAIL: {assessment.summary}",
            findings=legacy_findings,
            evidence=[{"ref": ref} for ref in assessment.evidence_refs],
            remediation=legacy_findings[0].remediation if legacy_findings else "",
            metadata=metadata,
        )

    if assessment.status == AssessmentStatus.NOT_ASSESSED:
        # Mandatory check that was not assessed must fail; non-mandatory warns. NEVER PASS.
        verdict: Verdict = "FAIL" if is_mandatory else "WARN"
        severity = "error" if is_mandatory else "warning"
        synthetic_id = stable_finding_id(assessment.rule_id, "not_assessed")
        unassessed_finding = Finding(
            id=synthetic_id,
            severity=severity,
            location=assessment.rule_id,
            description=f"Rule '{assessment.rule_id}' was NOT ASSESSED: {assessment.summary}",
            remediation="Provide required inputs or execute necessary verification step.",
            failure_mode="manual_review",
            metadata=metadata,
        )
        return VerdictReport(
            verdict=verdict,
            severity=severity,
            failure_mode="manual_review",
            summary=f"[NOT ASSESSED] {assessment.summary}",
            text=f"NOT ASSESSED: {assessment.summary}",
            findings=[unassessed_finding],
            remediation=unassessed_finding.remediation,
            metadata=metadata,
        )

    if assessment.status == AssessmentStatus.BLOCKED:
        # Blocked evaluation is a hard failure (cannot proceed). NEVER PASS.
        synthetic_id = stable_finding_id(assessment.rule_id, "blocked")
        blocked_finding = Finding(
            id=synthetic_id,
            severity="error",
            location=assessment.rule_id,
            description=f"Evaluation BLOCKED: {assessment.summary}",
            remediation="Resolve prerequisites or tool environment to unblock assessment.",
            failure_mode="environment",
            metadata=metadata,
        )
        return VerdictReport(
            verdict="FAIL",
            severity="error",
            failure_mode="environment",
            summary=f"[BLOCKED] {assessment.summary}",
            text=f"BLOCKED: {assessment.summary}",
            findings=[blocked_finding],
            remediation=blocked_finding.remediation,
            metadata=metadata,
        )

    raise ValueError(f"Unhandled assessment status: {assessment.status}")


def adapt_snapshot_to_verdict(snapshot: ReviewSnapshot) -> VerdictReport:
    """Aggregate a full ReviewSnapshot into a legacy VerdictReport envelope."""
    coverage = snapshot.coverage
    metadata: dict[str, Any] = {
        "project_key": snapshot.project_key,
        "rule_catalog_revision": snapshot.rule_catalog_revision,
        "total_rules": coverage.total_rules,
        "applicable_count": coverage.applicable_count,
        "passed_count": coverage.passed_count,
        "warned_count": coverage.warned_count,
        "failed_count": coverage.failed_count,
        "not_assessed_count": coverage.not_assessed_count,
        "blocked_count": coverage.blocked_count,
        "required_unassessed": coverage.required_unassessed,
    }

    all_findings: list[Finding] = []
    for assessment in snapshot.assessments:
        v_report = adapt_assessment_to_verdict(assessment)
        all_findings.extend(v_report.findings)

    # If any mandatory rule is required but unassessed/blocked, overall verdict is FAIL
    if coverage.required_unassessed or coverage.failed_count > 0 or coverage.blocked_count > 0:
        overall_verdict: Verdict = "FAIL"
        summary = (
            f"Review FAIL: {coverage.failed_count} failed, {coverage.blocked_count} blocked, "
            f"{len(coverage.required_unassessed)} required checks unassessed."
        )
    elif coverage.warned_count > 0:
        overall_verdict = "WARN"
        summary = f"Review WARN: {coverage.warned_count} warnings, all mandatory checks satisfied."
    else:
        overall_verdict = "PASS"
        summary = f"Review PASS: all {coverage.applicable_count} applicable checks verified."

    return VerdictReport(
        verdict=overall_verdict,
        severity=VerdictReport.severity_for(overall_verdict),
        summary=summary,
        text=summary,
        findings=all_findings,
        metadata=metadata,
    )

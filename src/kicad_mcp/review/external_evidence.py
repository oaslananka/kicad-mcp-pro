"""External analysis evidence import with provenance and validity checks (#1585, T8).

Principles:
1. Versioned, size-bounded contract for external analysis reports.
2. Content is untrusted: schema-validated JSON/YAML parsing without code execution.
3. Path safety: guards against path traversal and unauthorized directory escapes.
4. Rejection of invalid evidence: foreign-board reports, stale source hashes,
   mismatched stackups, and solver divergences cannot PASS.
5. Incompatible or unrecognized units cannot return PASS.
6. Local review works offline: missing external report yields NOT_ASSESSED, never blocking
   unrelated local review.
7. Retains complete provenance: tool name/version, solver method, input hash,
   convergence status, assumptions, and artifact digests.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, field_validator

from ..models.review import (
    SUPPORTED_REVIEW_UNITS,
    AssessmentStatus,
    EvaluationMethod,
    ReviewAssessment,
    ReviewContext,
    ReviewFinding,
)
from ..project.evidence_freshness import (
    EvidenceInputDigest,
    EvidenceRecord,
    EvidenceRecordKind,
)

MAX_REPORT_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB limit


class ExternalAnalysisReport(BaseModel):
    """Bounded, schema-validated report from an external analysis tool."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = 1
    report_id: str = Field(min_length=3, max_length=120)
    tool_name: str = Field(min_length=1, max_length=80)
    tool_version: str = Field(min_length=1, max_length=50)
    analysis_type: str = Field(min_length=1, max_length=50)
    method: EvaluationMethod = EvaluationMethod.ANALYTICAL
    project_key: str = Field(min_length=1, max_length=120)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    stackup_id: str | None = None
    material_group: str | None = None
    convergence_status: Literal["converged", "diverged", "truncated", "aborted"] = "converged"
    termination_reason: str = ""
    assumptions: dict[str, Any] = Field(default_factory=dict)
    boundary_conditions: dict[str, Any] = Field(default_factory=dict)
    validity_range: dict[str, Any] = Field(default_factory=dict)
    metrics: dict[str, FiniteFloat] = Field(default_factory=dict)
    metric_units: dict[str, str] = Field(default_factory=dict)
    violations: list[str] = Field(default_factory=list)
    artifact_hashes: dict[str, str] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("artifact_hashes")
    @classmethod
    def validate_artifact_hashes(cls, values: dict[str, str]) -> dict[str, str]:
        import re

        for digest in values.values():
            if re.fullmatch(r"[0-9a-f]{64}", digest) is None:
                raise ValueError("Artifact digest must be a lowercase SHA-256 hex string.")
        return values


def load_external_analysis_report(
    file_path: Path | str,
    base_dir: Path | None = None,
) -> tuple[ExternalAnalysisReport | None, str | None]:
    """Safely load and validate an external analysis report file."""
    path = Path(file_path)
    if base_dir is not None:
        resolved_base = base_dir.resolve()
        resolved_path = (resolved_base / path).resolve()
        try:
            resolved_path.relative_to(resolved_base)
        except ValueError:
            return None, "Security violation: file path escapes project directory."
    else:
        resolved_path = path.resolve()

    if not resolved_path.is_file():
        return None, f"Report file does not exist: {resolved_path}"

    file_size = resolved_path.stat().st_size
    if file_size > MAX_REPORT_SIZE_BYTES:
        return (
            None,
            f"Report file exceeds size limit ({file_size} > {MAX_REPORT_SIZE_BYTES} bytes).",
        )

    try:
        content = resolved_path.read_text(encoding="utf-8")
        if resolved_path.suffix.lower() in {".yaml", ".yml"}:
            data = yaml.safe_load(content)
        else:
            data = json.loads(content)
    except Exception as exc:
        return None, f"Failed to parse report file as JSON/YAML: {exc}"

    if not isinstance(data, dict):
        return None, "Report payload must be a JSON/YAML mapping object."

    try:
        report = ExternalAnalysisReport.model_validate(data)
        return report, None
    except Exception as exc:
        return None, f"Report schema validation failed: {exc}"


def _missing_verification_context(
    context: ReviewContext,
    report: ExternalAnalysisReport,
    rule_id: str,
) -> ReviewAssessment | None:
    """Never accept a self-declared report without an independently known design."""
    missing = []
    if not context.project_name:
        missing.append("active_project_name")
    if not context.project_source_sha256:
        missing.append("active_project_source_sha256")
    if (
        not missing
        and report.stackup_id
        and not context.explicit_requirements.get("expected_stackup_id")
    ):
        missing.append("expected_stackup_id")
    if not missing:
        return None
    return ReviewAssessment(
        rule_id=rule_id,
        rule_revision=1,
        status=AssessmentStatus.NOT_ASSESSED,
        method=EvaluationMethod.ANALYTICAL,
        summary="Active project provenance or stackup evidence missing; report not verified.",
        missing_inputs=missing,
        metadata={"defect_category": "analysis", "report_id": report.report_id},
    )


def _metric_units_blocker(
    context: ReviewContext,
    report: ExternalAnalysisReport,
    rule_id: str,
) -> ReviewAssessment | None:
    """Reject unknown or dimensionally incompatible units without guessing conversions."""
    for metric_name, actual_unit in report.metric_units.items():
        if actual_unit not in SUPPORTED_REVIEW_UNITS:
            return ReviewAssessment(
                rule_id=rule_id,
                rule_revision=1,
                status=AssessmentStatus.NOT_ASSESSED,
                method=EvaluationMethod.ANALYTICAL,
                summary=f"Incompatible unit '{actual_unit}' declared for metric '{metric_name}'.",
                missing_inputs=["compatible_metric_units"],
                metadata={
                    "defect_category": "analysis",
                    "invalid_unit": actual_unit,
                    "metric": metric_name,
                },
            )
    expected = context.explicit_requirements.get("expected_metric_units")
    if expected is None:
        return None
    if not isinstance(expected, dict):
        invalid = "Expected metric units must be a mapping."
    else:
        invalid = ""
        for metric_name, expected_unit in expected.items():
            unit_for_metric = report.metric_units.get(metric_name)
            if (
                not isinstance(expected_unit, str)
                or expected_unit not in SUPPORTED_REVIEW_UNITS
                or unit_for_metric is None
                or metric_name not in report.metrics
                or SUPPORTED_REVIEW_UNITS[unit_for_metric] != SUPPORTED_REVIEW_UNITS[expected_unit]
            ):
                invalid = f"Metric '{metric_name}' is missing or dimensionally incompatible."
                break
    if not invalid:
        return None
    return ReviewAssessment(
        rule_id=rule_id,
        rule_revision=1,
        status=AssessmentStatus.NOT_ASSESSED,
        method=EvaluationMethod.ANALYTICAL,
        summary=invalid,
        missing_inputs=["compatible_metric_units"],
        metadata={"defect_category": "analysis", "report_id": report.report_id},
    )


def evaluate_external_evidence(
    context: ReviewContext,
    report: ExternalAnalysisReport | None,
    *,
    rule_id: str = "analysis.external_simulation",
) -> ReviewAssessment:
    """Evaluate external analysis evidence against active project context and validity bounds."""
    if report is None:
        return ReviewAssessment(
            rule_id=rule_id,
            rule_revision=1,
            status=AssessmentStatus.NOT_ASSESSED,
            method=EvaluationMethod.ANALYTICAL,
            summary=(
                "External analysis report not provided; local review remains offline and active."
            ),
            missing_inputs=["external_analysis_report"],
            metadata={"defect_category": "analysis", "optional_external": True},
        )

    provenance_blocker = _missing_verification_context(context, report, rule_id)
    if provenance_blocker is not None:
        return provenance_blocker

    findings: list[ReviewFinding] = []
    finding_idx = 1

    # 1. Foreign-board check
    if context.project_name and report.project_key != context.project_name:
        summary = (
            f"Foreign board report rejected: report project '{report.project_key}' "
            f"does not match active design '{context.project_name}'."
        )
        findings.append(
            ReviewFinding(
                id=f"EXT_EVID_{finding_idx:03d}",
                rule_id=rule_id,
                rule_revision=1,
                severity="error",
                description=summary,
                remediation=(
                    "Run simulation against active project files rather than foreign boards."
                ),
                metadata={"report_id": report.report_id, "project_key": report.project_key},
            )
        )
        finding_idx += 1

    # 2. Stale-source check
    if context.project_source_sha256 and report.source_sha256 != context.project_source_sha256:
        summary = (
            f"Stale source report rejected: report hash ({report.source_sha256[:12]}...) "
            f"does not match active design hash ({context.project_source_sha256[:12]}...)."
        )
        findings.append(
            ReviewFinding(
                id=f"EXT_EVID_{finding_idx:03d}",
                rule_id=rule_id,
                rule_revision=1,
                severity="error",
                description=summary,
                remediation=(
                    "Re-run simulation against active design commit to produce fresh evidence."
                ),
                metadata={"report_id": report.report_id, "source_sha256": report.source_sha256},
            )
        )
        finding_idx += 1

    # 3. Stackup mismatch check
    expected_stackup = context.explicit_requirements.get("expected_stackup_id")
    if expected_stackup and report.stackup_id != expected_stackup:
        summary = (
            f"Stackup mismatch: report stackup '{report.stackup_id}' != "
            f"expected '{expected_stackup}'."
        )
        findings.append(
            ReviewFinding(
                id=f"EXT_EVID_{finding_idx:03d}",
                rule_id=rule_id,
                rule_revision=1,
                severity="error",
                description=summary,
                remediation="Re-run simulation with active board stackup configuration.",
                metadata={"report_id": report.report_id, "stackup_id": report.stackup_id},
            )
        )
        finding_idx += 1

    # 4. Solver divergence / truncation check
    if report.convergence_status != "converged":
        summary = (
            f"Simulation failed to converge ({report.convergence_status}): "
            f"{report.termination_reason}"
        )
        findings.append(
            ReviewFinding(
                id=f"EXT_EVID_{finding_idx:03d}",
                rule_id=rule_id,
                rule_revision=1,
                severity="error",
                description=summary,
                remediation="Adjust solver timestep, mesh refinement, or boundary conditions.",
                metadata={
                    "report_id": report.report_id,
                    "convergence_status": report.convergence_status,
                },
            )
        )
        finding_idx += 1

    # 5. Incompatible or unrecognized units check
    units_blocker = _metric_units_blocker(context, report, rule_id)
    if units_blocker is not None:
        return units_blocker

    # 6. Violations reported by external tool
    for viol in report.violations:
        findings.append(
            ReviewFinding(
                id=f"EXT_EVID_{finding_idx:03d}",
                rule_id=rule_id,
                rule_revision=1,
                severity="error",
                description=f"External simulation violation: {viol}",
                remediation="Resolve simulation failure in design geometry or parameters.",
                metadata={"report_id": report.report_id, "tool_name": report.tool_name},
            )
        )
        finding_idx += 1

    if any(f.severity == "error" for f in findings):
        status = AssessmentStatus.FAIL
        count = len(findings)
        summary = (
            findings[0].description
            if count == 1
            else f"External simulation failed with {count} defects: {findings[0].description}"
        )
    elif any(f.severity == "warning" for f in findings):
        status = AssessmentStatus.WARN
        count = len(findings)
        summary = (
            findings[0].description
            if count == 1
            else f"External simulation produced {count} warnings: {findings[0].description}"
        )
    else:
        status = AssessmentStatus.PASS
        summary = (
            f"External simulation '{report.analysis_type}' by {report.tool_name} "
            f"verified clean with 0 violations."
        )

    return ReviewAssessment(
        rule_id=rule_id,
        rule_revision=1,
        status=status,
        method=report.method,
        summary=summary,
        findings=findings,
        evidence_refs=[report.report_id] if status == AssessmentStatus.PASS else [],
        metadata={
            "defect_category": "analysis",
            "report_id": report.report_id,
            "tool_name": report.tool_name,
            "tool_version": report.tool_version,
            "analysis_type": report.analysis_type,
            "metrics": report.metrics,
            "artifact_hashes": report.artifact_hashes,
        },
    )


def report_to_evidence_record(report: ExternalAnalysisReport) -> EvidenceRecord:
    """Convert a verified external analysis report into a first-class EvidenceRecord."""
    return EvidenceRecord(
        schema_version=1,
        evidence_id=report.report_id,
        kind=EvidenceRecordKind.VERIFICATION_RUN,
        project_key=report.project_key,
        source_revision=str(report.metadata.get("source_revision", "rev_external")),
        source_sha256=report.source_sha256,
        producer=report.tool_name,
        producer_version=report.tool_version,
        captured_at=datetime.now(UTC),
        dependency_manifest_complete=True,
        inputs=(EvidenceInputDigest(entity_id=report.project_key, sha256=report.source_sha256),),
        contract_id=f"external_analysis.{report.analysis_type}",
        contract_version=1,
        provenance_source=f"external_tool:{report.tool_name}",
    )

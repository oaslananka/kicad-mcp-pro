"""Structured verdict report for high-traffic gate/check tools (work order P1-T4).

A ``VerdictReport`` carries both a human-readable ``text`` block (kept for clients that
only read text) and structured fields an agent can act on without parsing English:
a PASS/WARN/FAIL ``verdict``, a list of ``findings`` with stable, diffable IDs,
evidence, remediation, retryability, and an optional ``suggested_fix``. FastMCP
returns the model as MCP structured content alongside the JSON text, so both surfaces
stay in sync.
"""

from __future__ import annotations

import hashlib
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Verdict = Literal["PASS", "WARN", "FAIL"]
FailureMode = Literal["none", "design", "environment", "configuration", "manual_review"]

_FAIL_SEVERITIES = frozenset({"error", "fail", "failed", "critical"})
_WARN_SEVERITIES = frozenset({"warning", "warn", "marginal"})


def stable_finding_id(*parts: object) -> str:
    """Return a deterministic, diffable short id from rule + location parts.

    The id is a hash of the supplied parts (typically a rule/type and a location or
    description), so the same finding keeps the same id across runs — letting an agent
    prove a fix worked by diffing finding ids rather than re-reading prose.
    """
    raw = "|".join(str(part) for part in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


class SuggestedFix(BaseModel):
    """A concrete, machine-actionable next step for a finding."""

    model_config = ConfigDict(frozen=True)

    tool: str = ""
    args: dict[str, Any] = Field(default_factory=dict)


class Finding(BaseModel):
    """A single structured finding with a stable id and agent-actionable context."""

    model_config = ConfigDict(frozen=True)

    id: str
    severity: str = "error"
    location: str = ""
    description: str = ""
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    remediation: str = ""
    retryable: bool = False
    failure_mode: FailureMode = "design"
    suggested_fix: SuggestedFix | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class VerdictReport(BaseModel):
    """Stable verdict envelope returned by quality gates and critic tools.

    ``retryable`` is intentionally about retrying the same tool call without changing
    the design. Environment/configuration failures may be retryable after setup; design
    failures are non-transient and require remediation first.
    """

    model_config = ConfigDict(frozen=False)

    schema_version: str = "verdict.v1"
    # Human-readable rendering, preserved alongside the structured fields so text-only
    # clients keep working. FastMCP serializes the whole model to JSON text content.
    text: str = ""
    summary: str = ""
    verdict: Verdict = "PASS"
    severity: str = "info"
    failure_mode: FailureMode = "none"
    retryable: bool = False
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    remediation: str = ""
    findings: list[Finding] = Field(default_factory=list)
    next_action: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _normalize_envelope(self) -> VerdictReport:
        if self.severity == "info" and self.verdict != "PASS":
            self.severity = self.severity_for(self.verdict)
        if self.failure_mode == "none" and self.verdict != "PASS":
            self.failure_mode = self.failure_mode_for(self.verdict, self.retryable)
        if not self.evidence and self.findings:
            self.evidence = [item for finding in self.findings for item in finding.evidence]
        if not self.remediation and self.findings:
            remediations = [finding.remediation for finding in self.findings if finding.remediation]
            if remediations:
                self.remediation = remediations[0]
        return self

    @staticmethod
    def verdict_for(severities: list[str]) -> Verdict:
        """Aggregate a verdict from finding severities (FAIL > WARN > PASS)."""
        lowered = {str(severity).casefold() for severity in severities}
        if lowered & _FAIL_SEVERITIES:
            return "FAIL"
        if lowered & _WARN_SEVERITIES:
            return "WARN"
        return "PASS"

    @staticmethod
    def severity_for(verdict: Verdict) -> str:
        """Return the default machine severity for a PASS/WARN/FAIL verdict."""
        return {"PASS": "info", "WARN": "warning", "FAIL": "error"}[verdict]

    @staticmethod
    def failure_mode_for(verdict: Verdict, retryable: bool = False) -> FailureMode:
        """Return a conservative failure mode when a caller has no richer signal."""
        if verdict == "PASS":
            return "none"
        return "environment" if retryable else "design"

    @classmethod
    def from_text_verdict(
        cls,
        *,
        text: str,
        summary: str,
        verdict: Verdict,
        source: str,
        evidence: list[dict[str, Any]] | None = None,
        remediation: str = "",
        next_action: str = "",
        retryable: bool = False,
        failure_mode: FailureMode | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> VerdictReport:
        """Wrap a legacy text critic result in the standard verdict envelope."""
        resolved_failure_mode = failure_mode or cls.failure_mode_for(verdict, retryable)
        finding: Finding | None = None
        if verdict != "PASS":
            finding = Finding(
                id=stable_finding_id(source, verdict, summary),
                severity=cls.severity_for(verdict),
                location=source,
                description=summary,
                evidence=evidence or [],
                remediation=remediation,
                retryable=retryable,
                failure_mode=resolved_failure_mode,
            )
        return cls(
            text=text,
            summary=summary,
            verdict=verdict,
            severity=cls.severity_for(verdict),
            failure_mode=resolved_failure_mode,
            retryable=retryable,
            evidence=evidence or [],
            remediation=remediation,
            findings=[] if finding is None else [finding],
            next_action=next_action or remediation,
            metadata=metadata or {"source": source},
        )

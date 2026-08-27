"""Deterministic reporting for end-to-end PCB task outcome KPI evidence."""

from __future__ import annotations

import json

from .evidence_sanitization import validate_sanitized_evidence
from .task_outcome_scoring import RateKpi, TaskOutcomeSummary


def _sanitized_payload(summary: TaskOutcomeSummary) -> dict[str, object]:
    payload = summary.model_dump(mode="json", exclude_none=True)
    validate_sanitized_evidence(payload)
    return payload


def render_task_outcome_summary_json(summary: TaskOutcomeSummary) -> str:
    """Render one task-outcome summary as deterministic sanitized JSON."""
    payload = _sanitized_payload(summary)
    return json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n"


def _render_rate(label: str, kpi: RateKpi) -> str:
    rate = "n/a" if kpi.rate is None else f"{kpi.rate * 100:.1f}%"
    return (
        f"{label}: {rate} ({kpi.numerator}/{kpi.denominator}; "
        f"target >={kpi.target * 100:.1f}%; {kpi.status})"
    )


def render_task_outcome_summary_text(summary: TaskOutcomeSummary) -> str:
    """Render the headline KPI view from the same sanitized aggregate object."""
    _sanitized_payload(summary)
    failure_categories = "; ".join(
        f"{category}={count}" for category, count in sorted(summary.failure_categories.items())
    )
    if not failure_categories:
        failure_categories = "none"
    lines = [
        f"PCB Task Outcome — {summary.benchmark_id} {summary.benchmark_version}",
        (
            f"Attempts: {summary.attempts_total} total; {summary.valid_attempts} valid; "
            f"{summary.infrastructure_invalid_attempts} infrastructure-invalid; "
            f"{summary.successful_attempts} successful; {summary.failed_attempts} failed"
        ),
        _render_rate("PCB Design Task Success Rate", summary.task_success),
        _render_rate("Mutation Recovery", summary.mutation_recovery),
        (
            f"File Corruption: {summary.file_corruption_incidents} incidents "
            f"({summary.file_corruption_status})"
        ),
        _render_rate("Required DRC Execution", summary.required_drc_execution),
        _render_rate("Manufacturing Reproducibility", summary.manufacturing_reproducibility),
        (
            f"Integrity: {summary.duplicate_application_incidents} duplicate applications; "
            f"{summary.state_divergence_incidents} state divergences"
        ),
        f"Failure Categories: {failure_categories}",
    ]
    return "\n".join(lines) + "\n"


__all__ = [
    "render_task_outcome_summary_json",
    "render_task_outcome_summary_text",
]

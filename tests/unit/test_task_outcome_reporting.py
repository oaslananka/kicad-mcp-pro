"""Reporting tests for end-to-end PCB task outcome KPI evidence."""

from __future__ import annotations

import json

import pytest

import kicad_mcp.evals as evals
from kicad_mcp.evals.evidence_sanitization import EvidenceSanitizationError
from kicad_mcp.evals.task_outcome_reporting import (
    render_task_outcome_summary_json,
    render_task_outcome_summary_text,
)


def _rate(*, numerator: int, denominator: int, target: float, status: str) -> dict[str, object]:
    rate = numerator / denominator if denominator else None
    return {
        "numerator": numerator,
        "denominator": denominator,
        "rate": rate,
        "confidence_interval": None,
        "target": target,
        "status": status,
    }


def _summary(*, benchmark_id: str = "pcb-reference-suite") -> evals.TaskOutcomeSummary:
    return evals.TaskOutcomeSummary.model_validate(
        {
            "schema_version": "pcb-task-outcome-summary.v1",
            "benchmark_id": benchmark_id,
            "benchmark_version": "v1",
            "attempts_total": 3,
            "valid_attempts": 2,
            "infrastructure_invalid_attempts": 1,
            "successful_attempts": 1,
            "failed_attempts": 1,
            "failure_categories": {"provider": 1},
            "task_success": _rate(numerator=1, denominator=2, target=0.95, status="not_met"),
            "mutation_attempts": 4,
            "recovery_required_mutations": 2,
            "successful_recoveries": 2,
            "mutation_recovery": _rate(numerator=2, denominator=2, target=0.99, status="met"),
            "duplicate_application_incidents": 0,
            "state_divergence_incidents": 0,
            "file_corruption_incidents": 0,
            "file_corruption_status": "met",
            "drc_required_tasks": 2,
            "drc_executed_and_consumed_tasks": 2,
            "required_drc_execution": _rate(
                numerator=2,
                denominator=2,
                target=1.0,
                status="met",
            ),
            "manufacturing_release_tasks": 1,
            "manufacturing_reproducible_tasks": 1,
            "manufacturing_reproducibility": _rate(
                numerator=1,
                denominator=1,
                target=1.0,
                status="met",
            ),
        }
    )


def test_json_report_is_deterministic_sanitized_summary() -> None:
    rendered = render_task_outcome_summary_json(_summary())

    assert rendered.endswith("\n")
    payload = json.loads(rendered)
    assert payload["schema_version"] == "pcb-task-outcome-summary.v1"
    assert payload["benchmark_id"] == "pcb-reference-suite"
    assert payload["attempts_total"] == 3
    assert payload["task_success"]["rate"] == 0.5
    assert payload["failure_categories"] == {"provider": 1}
    assert rendered == render_task_outcome_summary_json(_summary())


def test_text_report_uses_same_headline_kpis_and_denominators() -> None:
    rendered = render_task_outcome_summary_text(_summary())

    assert rendered == (
        "PCB Task Outcome — pcb-reference-suite v1\n"
        "Attempts: 3 total; 2 valid; 1 infrastructure-invalid; 1 successful; 1 failed\n"
        "PCB Design Task Success Rate: 50.0% (1/2; target >=95.0%; not_met)\n"
        "Mutation Recovery: 100.0% (2/2; target >=99.0%; met)\n"
        "File Corruption: 0 incidents (met)\n"
        "Required DRC Execution: 100.0% (2/2; target >=100.0%; met)\n"
        "Manufacturing Reproducibility: 100.0% (1/1; target >=100.0%; met)\n"
        "Integrity: 0 duplicate applications; 0 state divergences\n"
        "Failure Categories: provider=1\n"
    )


def test_eval_package_exports_task_outcome_report_renderers() -> None:
    assert evals.render_task_outcome_summary_json is render_task_outcome_summary_json
    assert evals.render_task_outcome_summary_text is render_task_outcome_summary_text


@pytest.mark.parametrize(
    "renderer",
    [render_task_outcome_summary_json, render_task_outcome_summary_text],
)
def test_report_renderers_reject_sensitive_evidence(renderer) -> None:
    with pytest.raises(EvidenceSanitizationError, match="sensitive string"):
        renderer(_summary(benchmark_id="/home/private/pcb-reference-suite"))

"""Regression coverage for task-outcome mutation integrity scoring."""

from __future__ import annotations

import pytest

import kicad_mcp.evals as evals


def _contract() -> evals.BenchmarkContract:
    return evals.BenchmarkContract(
        benchmark_id="pcb-reference-suite",
        benchmark_version="v1",
        tasks=(
            evals.TaskContract(
                task_id="route-usb-board",
                task_class="pcb-edit",
                version="v1",
                stage_requirements={
                    stage: "required"
                    if stage in {"requirements", "pcb", "drc", "parse_reopen"}
                    else "not_applicable"
                    for stage in evals.ALL_TASK_STAGES
                },
            ),
        ),
        evidence_sufficiency=evals.EvidenceSufficiencyContract(
            minimum_valid_attempts=1,
            minimum_valid_attempts_by_task_class={"pcb-edit": 1},
            minimum_recovery_required_mutations=0,
            minimum_drc_required_tasks=1,
            minimum_manufacturing_release_tasks=0,
        ),
    )


def _attempt(mutation: evals.MutationEvidence) -> evals.AttemptRecord:
    return evals.AttemptRecord(
        attempt_id="integrity-attempt",
        task_id="route-usb-board",
        task_class="pcb-edit",
        task_contract_version="v1",
        benchmark_id="pcb-reference-suite",
        benchmark_version="v1",
        source_revision="a" * 40,
        kicad_version="10.0.5",
        toolchain_contract="toolchain-v1",
        agent="fixture-agent",
        model="fixture-model",
        provider="fixture-provider",
        mcp_profile="default",
        operating_mode="write",
        starting_state_digest="sha256:" + "b" * 64,
        timing=evals.TimingEvidence(
            started_at="2026-08-23T01:00:00+03:00",
            ended_at="2026-08-23T01:01:00+03:00",
        ),
        classification="success",
        retry_count=0,
        start_state="clean",
        manual_repair=False,
        stages=tuple(
            evals.StageEvidence(stage=stage, outcome="passed")
            for stage in ("requirements", "pcb", "drc", "parse_reopen")
        ),
        validations=(
            evals.ValidationEvidence(
                kind="drc",
                required=True,
                execution_attempted=True,
                execution_completed=True,
                result_consumed=True,
                disposition="resolved",
            ),
        ),
        mutations=(mutation,),
    )


@pytest.mark.parametrize(
    ("incident_field", "summary_field"),
    [
        ("duplicate_application_detected", "duplicate_application_incidents"),
        ("state_divergence_detected", "state_divergence_incidents"),
    ],
)
def test_integrity_incidents_are_hard_failures(
    incident_field: str,
    summary_field: str,
) -> None:
    mutation = evals.MutationEvidence(
        mutation_id="m-integrity",
        attempted=True,
        execution_state="completed",
        recovery_required=False,
        final_state_verified=False,
    ).model_copy(update={incident_field: True})

    summary = evals.aggregate_task_outcomes(_contract(), [_attempt(mutation)])

    assert getattr(summary, summary_field) == 1
    assert summary.successful_attempts == 0
    assert summary.failed_attempts == 1
    assert summary.task_success.status == "not_met"

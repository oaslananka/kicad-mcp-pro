"""Regression coverage for fail-closed required validation scoring."""

from __future__ import annotations

import kicad_mcp.evals as evals


def test_missing_required_erc_validation_fails_after_required_stage_passes() -> None:
    stage_requirements = {stage: "not_applicable" for stage in evals.ALL_TASK_STAGES}
    for stage in ("requirements", "pcb", "erc", "drc", "parse_reopen"):
        stage_requirements[stage] = "required"

    contract = evals.BenchmarkContract.model_validate(
        {
            "schema_version": "pcb-task-outcome.v1",
            "benchmark_id": "pcb-reference-suite",
            "benchmark_version": "v1",
            "tasks": [
                {
                    "task_id": "route-usb-board",
                    "task_class": "pcb-edit",
                    "version": "v1",
                    "stage_requirements": stage_requirements,
                }
            ],
            "evidence_sufficiency": {
                "minimum_valid_attempts": 1,
                "minimum_valid_attempts_by_task_class": {"pcb-edit": 1},
                "minimum_recovery_required_mutations": 0,
                "minimum_drc_required_tasks": 1,
                "minimum_manufacturing_release_tasks": 0,
                "confidence_level": 0.95,
                "interval_method": "wilson",
            },
        }
    )
    attempt = evals.AttemptRecord.model_validate(
        {
            "schema_version": "pcb-task-outcome.v1",
            "attempt_id": "erc-validation-missing",
            "task_id": "route-usb-board",
            "task_class": "pcb-edit",
            "task_contract_version": "v1",
            "benchmark_id": "pcb-reference-suite",
            "benchmark_version": "v1",
            "source_revision": "a" * 40,
            "kicad_version": "10.0.5",
            "toolchain_contract": "toolchain-v1",
            "agent": "fixture-agent",
            "model": "fixture-model",
            "provider": "fixture-provider",
            "mcp_profile": "default",
            "operating_mode": "write",
            "starting_state_digest": "sha256:" + "b" * 64,
            "timing": {
                "started_at": "2026-08-23T01:00:00+03:00",
                "ended_at": "2026-08-23T01:01:00+03:00",
            },
            "classification": "success",
            "retry_count": 0,
            "start_state": "clean",
            "manual_repair": False,
            "stages": [
                {"stage": stage, "outcome": "passed"}
                for stage in ("requirements", "pcb", "erc", "drc", "parse_reopen")
            ],
            "validations": [
                {
                    "kind": "drc",
                    "required": True,
                    "execution_attempted": True,
                    "execution_completed": True,
                    "result_consumed": True,
                    "disposition": "resolved",
                }
            ],
            "mutations": [],
        }
    )

    summary = evals.aggregate_task_outcomes(contract, [attempt])

    assert summary.successful_attempts == 0
    assert summary.failed_attempts == 1
    assert summary.failure_categories == {"unclassified_failure": 1}
    assert summary.required_drc_execution.status == "met"

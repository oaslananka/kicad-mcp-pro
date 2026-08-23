"""Scoring tests for end-to-end PCB task outcome evidence."""

from __future__ import annotations

from typing import Any

import pytest

import kicad_mcp.evals as evals


def _stage_requirements(*, manufacturing: bool = False) -> dict[str, str]:
    requirements = {stage: "not_applicable" for stage in evals.ALL_TASK_STAGES}
    for stage in ("requirements", "pcb", "drc", "parse_reopen"):
        requirements[stage] = "required"
    if manufacturing:
        requirements["manufacturing_generation"] = "required"
        requirements["manufacturing_reproducibility"] = "required"
    return requirements


def _contract(
    *,
    minimum_valid_attempts: int = 1,
    minimum_recovery_required_mutations: int = 0,
    minimum_drc_required_tasks: int = 1,
    minimum_manufacturing_release_tasks: int = 0,
    manufacturing: bool = False,
) -> evals.BenchmarkContract:
    return evals.BenchmarkContract.model_validate(
        {
            "schema_version": "pcb-task-outcome.v1",
            "benchmark_id": "pcb-reference-suite",
            "benchmark_version": "v1",
            "tasks": [
                {
                    "task_id": "route-usb-board",
                    "task_class": "pcb-edit",
                    "version": "v1",
                    "stage_requirements": _stage_requirements(manufacturing=manufacturing),
                }
            ],
            "evidence_sufficiency": {
                "minimum_valid_attempts": minimum_valid_attempts,
                "minimum_valid_attempts_by_task_class": {
                    "pcb-edit": minimum_valid_attempts,
                },
                "minimum_recovery_required_mutations": minimum_recovery_required_mutations,
                "minimum_drc_required_tasks": minimum_drc_required_tasks,
                "minimum_manufacturing_release_tasks": minimum_manufacturing_release_tasks,
                "confidence_level": 0.95,
                "interval_method": "wilson",
            },
        }
    )


def _attempt(
    attempt_id: str,
    *,
    classification: str = "success",
    drc_executed: bool = True,
    omit_stage: str | None = None,
    mutations: list[dict[str, Any]] | None = None,
    manufacturing: dict[str, Any] | None = None,
) -> evals.AttemptRecord:
    stages = [
        {"stage": "requirements", "outcome": "passed"},
        {"stage": "pcb", "outcome": "passed"},
        {"stage": "drc", "outcome": "passed"},
        {"stage": "parse_reopen", "outcome": "passed"},
    ]
    if manufacturing is not None:
        stages.extend(
            [
                {"stage": "manufacturing_generation", "outcome": "passed"},
                {"stage": "manufacturing_reproducibility", "outcome": "passed"},
            ]
        )
    if omit_stage is not None:
        stages = [stage for stage in stages if stage["stage"] != omit_stage]

    payload: dict[str, Any] = {
        "schema_version": "pcb-task-outcome.v1",
        "attempt_id": attempt_id,
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
        "classification": classification,
        "retry_count": 0,
        "start_state": "clean",
        "manual_repair": False,
        "stages": stages,
        "validations": [
            {
                "kind": "drc",
                "required": True,
                "execution_attempted": drc_executed,
                "execution_completed": drc_executed,
                "result_consumed": drc_executed,
                "disposition": "resolved" if drc_executed else "blocking",
            }
        ],
        "mutations": mutations or [],
    }
    failure_categories = {
        "task_failure": "design",
        "recovery_failure": "recovery",
        "provider_failure": "provider",
        "tool_failure": "tool",
        "infrastructure_invalid": "infrastructure",
    }
    if classification != "success":
        payload["failure_category"] = failure_categories[classification]
        payload["failure_reason_code"] = "fixture_failure"
    if classification == "infrastructure_invalid":
        payload["stages"] = []
        payload["validations"] = []
        payload["mutations"] = []
        payload["infrastructure_evidence"] = {
            "reason_code": "fixture_failure",
            "reviewed": True,
            "task_execution_started": False,
        }
    if manufacturing is not None:
        payload["manufacturing"] = manufacturing
    return evals.AttemptRecord.model_validate(payload)


def _recovery_mutation(mutation_id: str, *, succeeded: bool) -> dict[str, Any]:
    return {
        "mutation_id": mutation_id,
        "attempted": True,
        "execution_state": "interrupted",
        "recovery_required": True,
        "recovery_succeeded": succeeded,
        "duplicate_application_detected": False,
        "state_divergence_detected": False,
        "corruption_detected": False,
        "final_state_verified": succeeded,
    }


def _manufacturing(*, comparison: str = "byte_identical") -> dict[str, Any]:
    return {
        "required": True,
        "generation_completed": True,
        "regeneration_completed": True,
        "comparison": comparison,
        "artifact_manifest_digests": [
            "sha256:" + "c" * 64,
            "sha256:" + "d" * 64,
        ],
    }


def test_eval_package_exposes_task_outcome_scoring_contract() -> None:
    assert evals.TASK_OUTCOME_SUMMARY_SCHEMA_VERSION == "pcb-task-outcome-summary.v1"
    assert evals.TaskOutcomeSummary is not None
    assert evals.aggregate_task_outcomes is not None


def test_provider_failure_stays_in_denominator_and_infrastructure_invalid_does_not() -> None:
    contract = _contract(minimum_valid_attempts=2, minimum_drc_required_tasks=2)
    summary = evals.aggregate_task_outcomes(
        contract,
        [
            _attempt("success-1"),
            _attempt("provider-1", classification="provider_failure"),
            _attempt("invalid-1", classification="infrastructure_invalid"),
        ],
    )

    assert summary.attempts_total == 3
    assert summary.valid_attempts == 2
    assert summary.infrastructure_invalid_attempts == 1
    assert summary.successful_attempts == 1
    assert summary.task_success.numerator == 1
    assert summary.task_success.denominator == 2
    assert summary.task_success.rate == 0.5
    assert summary.task_success.status == "not_met"
    assert summary.failure_categories == {"provider": 1}


def test_missing_required_stage_fails_success_classification_closed() -> None:
    summary = evals.aggregate_task_outcomes(
        _contract(),
        [_attempt("missing-parse", omit_stage="parse_reopen")],
    )

    assert summary.successful_attempts == 0
    assert summary.failed_attempts == 1
    assert summary.failure_categories == {"unclassified_failure": 1}
    assert summary.task_success.status == "not_met"


def test_recovery_drc_and_manufacturing_metrics_use_explicit_denominators() -> None:
    contract = _contract(
        minimum_valid_attempts=2,
        minimum_recovery_required_mutations=2,
        minimum_drc_required_tasks=2,
        minimum_manufacturing_release_tasks=2,
        manufacturing=True,
    )
    summary = evals.aggregate_task_outcomes(
        contract,
        [
            _attempt(
                "recovered",
                mutations=[_recovery_mutation("m1", succeeded=True)],
                manufacturing=_manufacturing(),
            ),
            _attempt(
                "recovery-failed",
                classification="recovery_failure",
                mutations=[_recovery_mutation("m2", succeeded=False)],
                manufacturing=_manufacturing(),
            ),
        ],
    )

    assert summary.mutation_recovery.numerator == 1
    assert summary.mutation_recovery.denominator == 2
    assert summary.mutation_recovery.rate == 0.5
    assert summary.mutation_recovery.status == "not_met"
    assert summary.required_drc_execution.rate == 1.0
    assert summary.required_drc_execution.status == "met"
    assert summary.manufacturing_reproducibility.rate == 1.0
    assert summary.manufacturing_reproducibility.status == "met"


def test_required_drc_not_executed_fails_task_and_drc_target() -> None:
    summary = evals.aggregate_task_outcomes(
        _contract(),
        [_attempt("drc-skipped", drc_executed=False)],
    )

    assert summary.successful_attempts == 0
    assert summary.required_drc_execution.numerator == 0
    assert summary.required_drc_execution.denominator == 1
    assert summary.required_drc_execution.status == "not_met"


def test_corruption_is_a_hard_failure_even_when_attempt_is_classified_success() -> None:
    mutation = {
        "mutation_id": "m-corrupt",
        "attempted": True,
        "execution_state": "completed",
        "recovery_required": False,
        "duplicate_application_detected": False,
        "state_divergence_detected": False,
        "corruption_detected": True,
        "final_state_verified": False,
    }
    summary = evals.aggregate_task_outcomes(
        _contract(),
        [_attempt("corrupt", mutations=[mutation])],
    )

    assert summary.file_corruption_incidents == 1
    assert summary.file_corruption_status == "not_met"
    assert summary.successful_attempts == 0


def test_zero_or_below_minimum_denominator_is_insufficient_evidence() -> None:
    contract = _contract(
        minimum_valid_attempts=2,
        minimum_recovery_required_mutations=1,
        minimum_drc_required_tasks=2,
        minimum_manufacturing_release_tasks=1,
    )
    summary = evals.aggregate_task_outcomes(contract, [_attempt("only-one")])

    assert summary.task_success.status == "insufficient_evidence"
    assert summary.mutation_recovery.rate is None
    assert summary.mutation_recovery.status == "insufficient_evidence"
    assert summary.required_drc_execution.status == "insufficient_evidence"
    assert summary.manufacturing_reproducibility.rate is None
    assert summary.manufacturing_reproducibility.status == "insufficient_evidence"
    assert summary.file_corruption_status == "insufficient_evidence"


def test_wilson_interval_is_reported_and_aggregation_is_input_order_stable() -> None:
    contract = _contract(minimum_valid_attempts=2, minimum_drc_required_tasks=2)
    attempts = [_attempt("success-1"), _attempt("provider-1", classification="provider_failure")]

    forward = evals.aggregate_task_outcomes(contract, attempts)
    reverse = evals.aggregate_task_outcomes(contract, list(reversed(attempts)))

    assert forward.model_dump(mode="json") == reverse.model_dump(mode="json")
    assert forward.task_success.confidence_interval is not None
    assert forward.task_success.confidence_interval.lower == pytest.approx(0.09453120573423074)
    assert forward.task_success.confidence_interval.upper == pytest.approx(0.9054687942657693)


def test_attempt_identity_mismatch_is_rejected_instead_of_cross_scored() -> None:
    record = _attempt("wrong-version").model_copy(update={"benchmark_version": "v2"})

    with pytest.raises(evals.TaskOutcomeScoringError, match="benchmark"):
        evals.aggregate_task_outcomes(_contract(), [record])

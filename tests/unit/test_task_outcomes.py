"""Contract tests for versioned end-to-end task outcome evidence."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

import kicad_mcp.evals as evals


def valid_stage_requirements() -> dict[str, str]:
    requirements = {stage: "not_applicable" for stage in evals.ALL_TASK_STAGES}
    for stage in ("requirements", "pcb", "drc", "parse_reopen"):
        requirements[stage] = "required"
    return requirements


def valid_benchmark_payload() -> dict[str, Any]:
    return {
        "schema_version": "pcb-task-outcome.v1",
        "benchmark_id": "pcb-reference-suite",
        "benchmark_version": "v1",
        "tasks": [
            {
                "task_id": "route-usb-board",
                "task_class": "pcb-edit",
                "version": "v1",
                "stage_requirements": valid_stage_requirements(),
            }
        ],
        "evidence_sufficiency": {
            "minimum_valid_attempts": 20,
            "minimum_valid_attempts_by_task_class": {"pcb-edit": 10},
            "minimum_recovery_required_mutations": 10,
            "minimum_drc_required_tasks": 10,
            "minimum_manufacturing_release_tasks": 0,
            "confidence_level": 0.95,
            "interval_method": "wilson",
        },
    }


def valid_attempt_payload(classification: str = "success") -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": "pcb-task-outcome.v1",
        "attempt_id": "attempt-001",
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
        "stages": [
            {"stage": "requirements", "outcome": "passed"},
            {"stage": "pcb", "outcome": "passed"},
            {"stage": "drc", "outcome": "passed"},
            {"stage": "parse_reopen", "outcome": "passed"},
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
    return payload


def test_eval_package_exposes_task_outcome_v1_contract() -> None:
    assert evals.TASK_OUTCOME_SCHEMA_VERSION == "pcb-task-outcome.v1"
    assert evals.AttemptRecord is not None
    assert evals.BenchmarkContract is not None


def test_benchmark_contract_accepts_complete_v1_payload() -> None:
    contract = evals.BenchmarkContract.model_validate(valid_benchmark_payload())
    assert contract.schema_version == "pcb-task-outcome.v1"
    assert contract.tasks[0].task_id == "route-usb-board"


def test_benchmark_contract_requires_explicit_stage_requirement_for_every_stage() -> None:
    payload = valid_benchmark_payload()
    payload["tasks"][0]["stage_requirements"].pop("drc")

    with pytest.raises(ValidationError, match="stage requirements"):
        evals.BenchmarkContract.model_validate(payload)


def test_benchmark_contract_rejects_unknown_schema_version() -> None:
    payload = valid_benchmark_payload()
    payload["schema_version"] = "pcb-task-outcome.v2"

    with pytest.raises(ValidationError):
        evals.BenchmarkContract.model_validate(payload)


def test_benchmark_contract_rejects_unknown_fields() -> None:
    payload = valid_benchmark_payload()
    payload["unexpected"] = True

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        evals.BenchmarkContract.model_validate(payload)


def test_attempt_record_accepts_complete_v1_payload() -> None:
    record = evals.AttemptRecord.model_validate(valid_attempt_payload())
    assert record.schema_version == "pcb-task-outcome.v1"
    assert record.classification == "success"
    assert record.benchmark_id == "pcb-reference-suite"


def test_attempt_record_rejects_extra_fields() -> None:
    payload = valid_attempt_payload()
    payload["raw_response"] = "must never be accepted"

    with pytest.raises(ValidationError):
        evals.AttemptRecord.model_validate(payload)


def test_success_attempt_rejects_failure_metadata() -> None:
    payload = valid_attempt_payload()
    payload["failure_category"] = "provider"
    payload["failure_reason_code"] = "rate_limited"

    with pytest.raises(ValidationError, match="success"):
        evals.AttemptRecord.model_validate(payload)


def test_provider_failure_requires_provider_category() -> None:
    payload = valid_attempt_payload(classification="provider_failure")
    payload["failure_category"] = "tool"

    with pytest.raises(ValidationError, match="provider"):
        evals.AttemptRecord.model_validate(payload)


def test_timing_rejects_naive_or_reverse_timestamps() -> None:
    payload = valid_attempt_payload()
    payload["timing"] = {
        "started_at": "2026-08-23T01:00:00+03:00",
        "ended_at": "2026-08-23T00:59:00+03:00",
    }

    with pytest.raises(ValidationError, match="ended_at"):
        evals.AttemptRecord.model_validate(payload)

    payload = valid_attempt_payload()
    payload["timing"] = {
        "started_at": "2026-08-23T01:00:00",
        "ended_at": "2026-08-23T01:01:00",
    }

    with pytest.raises(ValidationError, match="timezone-aware"):
        evals.AttemptRecord.model_validate(payload)


def test_validation_evidence_rejects_consumed_without_completion() -> None:
    payload = valid_attempt_payload()
    payload["validations"][0]["execution_completed"] = False

    with pytest.raises(ValidationError, match="consumed validation"):
        evals.AttemptRecord.model_validate(payload)


def test_attempt_rejects_duplicate_stage_evidence() -> None:
    payload = valid_attempt_payload()
    payload["stages"].append({"stage": "drc", "outcome": "failed"})

    with pytest.raises(ValidationError, match="stages must be unique"):
        evals.AttemptRecord.model_validate(payload)

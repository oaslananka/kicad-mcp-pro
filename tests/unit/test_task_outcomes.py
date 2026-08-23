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


def test_parse_attempt_record_accepts_complete_v1_mapping() -> None:
    record = evals.parse_attempt_record(valid_attempt_payload())
    assert record.schema_version == "pcb-task-outcome.v1"
    assert record.classification == "success"


def test_parse_benchmark_contract_rejects_v2_mapping() -> None:
    payload = valid_benchmark_payload()
    payload["schema_version"] = "pcb-task-outcome.v2"

    with pytest.raises(ValidationError):
        evals.parse_benchmark_contract(payload)


def test_attempt_render_is_byte_reproducible() -> None:
    record = evals.parse_attempt_record(valid_attempt_payload())
    first_render = evals.render_attempt_record(record).encode()
    second_render = evals.render_attempt_record(record).encode()

    assert first_render == second_render


def test_attempt_render_ends_with_one_newline_and_sorted_keys() -> None:
    rendered = evals.render_attempt_record(evals.parse_attempt_record(valid_attempt_payload()))
    assert rendered.endswith("\n")
    assert not rendered.endswith("\n\n")
    assert rendered.index('"agent"') < rendered.index('"attempt_id"')


def test_attempt_render_rejects_private_path_values() -> None:
    payload = valid_attempt_payload()
    payload["agent"] = "/home/private/agent-config"
    record = evals.parse_attempt_record(payload)

    with pytest.raises(evals.EvidenceSanitizationError):
        evals.render_attempt_record(record)


def test_task_contract_predeclares_validation_exception_reason_codes() -> None:
    payload = valid_benchmark_payload()
    payload["tasks"][0]["validation_exception_reason_codes"] = {"drc": ["kicad_cli_unavailable"]}

    contract = evals.BenchmarkContract.model_validate(payload)

    assert contract.tasks[0].validation_exception_reason_codes == {
        "drc": ("kicad_cli_unavailable",)
    }


def test_attempt_start_state_requires_reviewed_recovery_label() -> None:
    payload = valid_attempt_payload()
    payload["start_state"] = "reviewed_recovered"
    record = evals.AttemptRecord.model_validate(payload)
    assert record.start_state == "reviewed_recovered"

    payload["start_state"] = "recovered"
    with pytest.raises(ValidationError):
        evals.AttemptRecord.model_validate(payload)


def test_infrastructure_invalid_requires_reviewed_pre_task_evidence() -> None:
    payload = valid_attempt_payload(classification="infrastructure_invalid")

    with pytest.raises(ValidationError, match="infrastructure-invalid evidence"):
        evals.AttemptRecord.model_validate(payload)


def test_mutation_evidence_records_attempt_and_execution_state() -> None:
    evidence = evals.MutationEvidence.model_validate(
        {
            "mutation_id": "mutation-001",
            "attempted": True,
            "execution_state": "interrupted",
            "recovery_required": True,
            "recovery_succeeded": False,
            "duplicate_application_detected": False,
            "state_divergence_detected": False,
            "corruption_detected": False,
            "final_state_verified": True,
        }
    )

    assert evidence.attempted is True
    assert evidence.execution_state == "interrupted"


def test_mutation_recovery_result_requires_recovery_denominator() -> None:
    with pytest.raises(ValidationError, match="recovery result"):
        evals.MutationEvidence.model_validate(
            {
                "mutation_id": "mutation-001",
                "attempted": True,
                "execution_state": "completed",
                "recovery_required": False,
                "recovery_succeeded": True,
                "final_state_verified": True,
            }
        )


def test_manufacturing_comparison_records_both_artifact_set_digests() -> None:
    evidence = evals.ManufacturingEvidence.model_validate(
        {
            "required": True,
            "generation_completed": True,
            "regeneration_completed": True,
            "comparison": "byte_identical",
            "artifact_manifest_digests": [
                "sha256:" + "a" * 64,
                "sha256:" + "b" * 64,
            ],
        }
    )

    assert len(evidence.artifact_manifest_digests or ()) == 2


def test_task_contract_rejects_exception_policy_for_not_applicable_validation() -> None:
    payload = valid_benchmark_payload()
    payload["tasks"][0]["stage_requirements"]["erc"] = "not_applicable"
    payload["tasks"][0]["validation_exception_reason_codes"] = {"erc": ["erc_engine_unavailable"]}

    with pytest.raises(ValidationError, match="exceptions require"):
        evals.BenchmarkContract.model_validate(payload)


def test_infrastructure_invalid_evidence_reason_must_match_failure_reason() -> None:
    payload = valid_attempt_payload(classification="infrastructure_invalid")
    payload["infrastructure_evidence"] = {
        "reason_code": "different_reason",
        "reviewed": True,
        "task_execution_started": False,
    }

    with pytest.raises(ValidationError, match="reason must match"):
        evals.AttemptRecord.model_validate(payload)


def test_infrastructure_invalid_accepts_reviewed_pre_task_evidence() -> None:
    payload = valid_attempt_payload(classification="infrastructure_invalid")
    payload["infrastructure_evidence"] = {
        "reason_code": "fixture_failure",
        "reviewed": True,
        "task_execution_started": False,
    }

    record = evals.AttemptRecord.model_validate(payload)
    assert record.infrastructure_evidence is not None
    assert record.infrastructure_evidence.reviewed is True
    assert record.infrastructure_evidence.task_execution_started is False


def test_non_infrastructure_attempt_rejects_infrastructure_evidence() -> None:
    payload = valid_attempt_payload()
    payload["infrastructure_evidence"] = {
        "reason_code": "fixture_failure",
        "reviewed": True,
        "task_execution_started": False,
    }

    with pytest.raises(ValidationError, match="only valid"):
        evals.AttemptRecord.model_validate(payload)


def test_manufacturing_comparison_requires_both_artifact_set_digests() -> None:
    with pytest.raises(ValidationError, match="both artifact-set manifest digests"):
        evals.ManufacturingEvidence.model_validate(
            {
                "required": True,
                "generation_completed": True,
                "regeneration_completed": True,
                "comparison": "byte_identical",
            }
        )

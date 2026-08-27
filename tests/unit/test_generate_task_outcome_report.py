"""CLI integration tests for deterministic task-outcome KPI reports."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType
from typing import Any

import kicad_mcp.evals as evals

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "generate_task_outcome_report.py"


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("generate_task_outcome_report", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _requirements() -> dict[str, str]:
    requirements = {stage: "not_applicable" for stage in evals.ALL_TASK_STAGES}
    for stage in ("requirements", "pcb", "drc", "parse_reopen"):
        requirements[stage] = "required"
    return requirements


def _contract() -> evals.BenchmarkContract:
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
                    "stage_requirements": _requirements(),
                }
            ],
            "evidence_sufficiency": {
                "minimum_valid_attempts": 2,
                "minimum_valid_attempts_by_task_class": {"pcb-edit": 2},
                "minimum_recovery_required_mutations": 0,
                "minimum_drc_required_tasks": 2,
                "minimum_manufacturing_release_tasks": 0,
            },
        }
    )


def _attempt_payload(attempt_id: str, *, classification: str) -> dict[str, Any]:
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
            "started_at": "2026-08-27T20:00:00+03:00",
            "ended_at": "2026-08-27T20:01:00+03:00",
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
    }
    if classification != "success":
        categories = {
            "provider_failure": "provider",
            "infrastructure_invalid": "infrastructure",
        }
        payload["failure_category"] = categories[classification]
        payload["failure_reason_code"] = "fixture_failure"
    if classification == "infrastructure_invalid":
        payload["stages"] = []
        payload["validations"] = []
        payload["infrastructure_evidence"] = {
            "reason_code": "fixture_failure",
            "reviewed": True,
            "task_execution_started": False,
        }
    return payload


def _write_attempt(path: Path, attempt_id: str, classification: str) -> evals.AttemptRecord:
    record = evals.AttemptRecord.model_validate(
        _attempt_payload(attempt_id, classification=classification)
    )
    path.write_text(evals.render_attempt_record(record), encoding="utf-8")
    return record


def test_cli_writes_json_and_text_from_one_aggregate(tmp_path: Path) -> None:
    module = _load_script()
    contract = _contract()
    contract_path = tmp_path / "contract.json"
    success_path = tmp_path / "success.json"
    provider_path = tmp_path / "provider.json"
    invalid_path = tmp_path / "infra.json"
    json_output = tmp_path / "reports" / "summary.json"
    text_output = tmp_path / "reports" / "summary.txt"

    contract_path.write_text(evals.render_benchmark_contract(contract), encoding="utf-8")
    success = _write_attempt(success_path, "attempt-success", "success")
    provider = _write_attempt(provider_path, "attempt-provider", "provider_failure")
    invalid = _write_attempt(invalid_path, "attempt-infra", "infrastructure_invalid")

    result = module.main(
        [
            "--contract",
            str(contract_path),
            "--attempt",
            str(success_path),
            "--attempt",
            str(provider_path),
            "--attempt",
            str(invalid_path),
            "--json-output",
            str(json_output),
            "--text-output",
            str(text_output),
        ]
    )

    assert result == 0
    summary = evals.aggregate_task_outcomes(contract, [success, provider, invalid])
    assert json_output.read_text(encoding="utf-8") == evals.render_task_outcome_summary_json(
        summary
    )
    assert text_output.read_text(encoding="utf-8") == evals.render_task_outcome_summary_text(
        summary
    )
    assert (
        json.loads(json_output.read_text(encoding="utf-8"))["infrastructure_invalid_attempts"] == 1
    )


def test_cli_invalid_attempt_fails_closed_before_writing_outputs(
    tmp_path: Path,
    capsys,
) -> None:
    module = _load_script()
    contract_path = tmp_path / "contract.json"
    attempt_path = tmp_path / "invalid-attempt.json"
    json_output = tmp_path / "summary.json"
    text_output = tmp_path / "summary.txt"
    contract_path.write_text(evals.render_benchmark_contract(_contract()), encoding="utf-8")
    payload = _attempt_payload("attempt-invalid", classification="success")
    payload["unexpected"] = "field"
    attempt_path.write_text(json.dumps(payload), encoding="utf-8")

    result = module.main(
        [
            "--contract",
            str(contract_path),
            "--attempt",
            str(attempt_path),
            "--json-output",
            str(json_output),
            "--text-output",
            str(text_output),
        ]
    )

    captured = capsys.readouterr()
    assert result != 0
    assert "task outcome report failed" in captured.err
    assert not json_output.exists()
    assert not text_output.exists()


def test_cli_refuses_to_overwrite_input_evidence(tmp_path: Path, capsys) -> None:
    module = _load_script()
    contract = _contract()
    contract_path = tmp_path / "contract.json"
    attempt_path = tmp_path / "attempt.json"
    text_output = tmp_path / "summary.txt"
    contract_path.write_text(evals.render_benchmark_contract(contract), encoding="utf-8")
    _write_attempt(attempt_path, "attempt-success", "success")
    original_attempt = attempt_path.read_text(encoding="utf-8")

    result = module.main(
        [
            "--contract",
            str(contract_path),
            "--attempt",
            str(attempt_path),
            "--json-output",
            str(attempt_path),
            "--text-output",
            str(text_output),
        ]
    )

    captured = capsys.readouterr()
    assert result != 0
    assert "must not overwrite input evidence" in captured.err
    assert attempt_path.read_text(encoding="utf-8") == original_attempt
    assert not text_output.exists()


def test_cli_output_directory_failure_returns_clean_nonzero(tmp_path: Path, capsys) -> None:
    module = _load_script()
    contract_path = tmp_path / "contract.json"
    attempt_path = tmp_path / "attempt.json"
    blocked_parent = tmp_path / "not-a-directory"
    blocked_parent.write_text("occupied", encoding="utf-8")
    contract_path.write_text(evals.render_benchmark_contract(_contract()), encoding="utf-8")
    _write_attempt(attempt_path, "attempt-success", "success")

    result = module.main(
        [
            "--contract",
            str(contract_path),
            "--attempt",
            str(attempt_path),
            "--json-output",
            str(blocked_parent / "summary.json"),
            "--text-output",
            str(tmp_path / "summary.txt"),
        ]
    )

    captured = capsys.readouterr()
    assert result != 0
    assert "task outcome report failed" in captured.err
    assert not (tmp_path / "summary.txt").exists()

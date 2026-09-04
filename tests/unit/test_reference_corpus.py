"""Contracts for publishable real-board reference corpus evidence."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from pydantic import ValidationError

import kicad_mcp.evals as evals


def _manifest_payload(
    evidence_digest: str | None = None, reference_inputs_digest: str | None = None
) -> dict[str, Any]:
    return {
        "schema_version": "pcb-reference-board.v1",
        "board_id": "stm32-usbc-reference",
        "benchmark_id": "reference-board-suite",
        "benchmark_version": "v1",
        "reference_inputs_digest": reference_inputs_digest or "sha256:" + "1" * 64,
        "attempts": [
            {
                "attempt_id": "attempt-001",
                "directory": "attempts/attempt-001",
                "evidence_digest": evidence_digest or "sha256:" + "0" * 64,
            }
        ],
    }


def _event_payload() -> dict[str, Any]:
    return {
        "schema_version": "pcb-reference-agent-log.v1",
        "attempt_id": "attempt-001",
        "sequence": 1,
        "timestamp": "2026-08-29T20:00:00+03:00",
        "event_type": "tool_call",
        "name": "pcb_add_via",
        "status": "completed",
        "details": {"attempt": 1, "cached": False},
    }


def test_eval_package_exposes_reference_corpus_contract() -> None:
    assert evals.ReferenceBoardManifest is not None
    assert evals.ReferenceAgentLogEvent is not None
    assert evals.ReferenceCorpusError is not None
    assert evals.compute_attempt_evidence_digest is not None
    assert evals.compute_reference_inputs_digest is not None


def test_reference_attempt_entry_requires_sha256_evidence_digest() -> None:
    payload = _manifest_payload()["attempts"][0]
    payload["evidence_digest"] = "sha256:" + "a" * 64

    entry = evals.ReferenceAttemptEntry.model_validate(payload)

    assert entry.evidence_digest == "sha256:" + "a" * 64


def test_reference_attempt_entry_rejects_missing_evidence_digest() -> None:
    payload = _manifest_payload()["attempts"][0]
    payload.pop("evidence_digest")

    with pytest.raises(ValidationError):
        evals.ReferenceAttemptEntry.model_validate(payload)


def test_reference_manifest_accepts_canonical_attempt_directory() -> None:
    manifest = evals.ReferenceBoardManifest.model_validate(_manifest_payload())
    assert manifest.board_id == "stm32-usbc-reference"
    assert manifest.attempts[0].directory == "attempts/attempt-001"


@pytest.mark.parametrize(
    "directory",
    [
        "/opt/attempt-001",
        "attempts/../attempt-001",
        "attempts\\attempt-001",
        "attempts/nested/attempt-001",
        "./attempts/attempt-001",
    ],
)
def test_reference_manifest_rejects_noncanonical_attempt_directory(directory: str) -> None:
    payload = _manifest_payload()
    payload["attempts"][0]["directory"] = directory

    with pytest.raises(ValidationError, match="attempts/<attempt-id>"):
        evals.ReferenceBoardManifest.model_validate(payload)


def test_reference_manifest_rejects_duplicate_attempt_ids_and_directories() -> None:
    payload = _manifest_payload()
    payload["attempts"].append(dict(payload["attempts"][0]))

    with pytest.raises(ValidationError, match="unique"):
        evals.ReferenceBoardManifest.model_validate(payload)


def test_reference_agent_log_event_requires_attempt_identity() -> None:
    payload = _event_payload()
    payload.pop("attempt_id")

    with pytest.raises(ValidationError):
        evals.ReferenceAgentLogEvent.model_validate(payload)


def test_reference_agent_log_event_accepts_scalar_details() -> None:
    event = evals.ReferenceAgentLogEvent.model_validate(_event_payload())
    assert event.sequence == 1
    assert event.details == {"attempt": 1, "cached": False}


def test_reference_agent_log_event_requires_timezone_aware_timestamp() -> None:
    payload = _event_payload()
    payload["timestamp"] = "2026-08-29T20:00:00"

    with pytest.raises(ValidationError, match="timezone-aware"):
        evals.ReferenceAgentLogEvent.model_validate(payload)


def test_reference_agent_log_event_rejects_nested_details() -> None:
    payload = _event_payload()
    payload["details"] = {"nested": {"raw": "not allowed"}}

    with pytest.raises(ValidationError):
        evals.ReferenceAgentLogEvent.model_validate(payload)


def test_reference_agent_log_event_rejects_unsafe_evidence_value() -> None:
    payload = _event_payload()
    payload["details"] = {"location": "/home/private/project.kicad_pcb"}

    with pytest.raises(ValueError, match="sensitive"):
        evals.ReferenceAgentLogEvent.model_validate(payload)


def _stage_requirements() -> dict[str, str]:
    requirements = {stage: "not_applicable" for stage in evals.ALL_TASK_STAGES}
    for stage in ("requirements", "schematic", "erc", "pcb", "drc", "parse_reopen"):
        requirements[stage] = "required"
    return requirements


def _benchmark_payload() -> dict[str, Any]:
    return {
        "schema_version": "pcb-task-outcome.v1",
        "benchmark_id": "reference-board-suite",
        "benchmark_version": "v1",
        "tasks": [
            {
                "task_id": "stm32-usbc-reference",
                "task_class": "reference-board",
                "version": "v1",
                "stage_requirements": _stage_requirements(),
            }
        ],
        "evidence_sufficiency": {
            "minimum_valid_attempts": 1,
            "minimum_valid_attempts_by_task_class": {"reference-board": 1},
            "minimum_recovery_required_mutations": 0,
            "minimum_drc_required_tasks": 1,
            "minimum_manufacturing_release_tasks": 0,
        },
    }


def _attempt_payload(
    attempt_id: str = "attempt-001",
    *,
    classification: str = "success",
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": "pcb-task-outcome.v1",
        "attempt_id": attempt_id,
        "task_id": "stm32-usbc-reference",
        "task_class": "reference-board",
        "task_contract_version": "v1",
        "benchmark_id": "reference-board-suite",
        "benchmark_version": "v1",
        "source_revision": "a" * 40,
        "kicad_version": "10.0.5",
        "toolchain_contract": "reference-toolchain-v1",
        "agent": "fixture-agent",
        "model": "fixture-model",
        "provider": "fixture-provider",
        "mcp_profile": "pcb",
        "operating_mode": "write",
        "starting_state_digest": "sha256:" + "b" * 64,
        "timing": {
            "started_at": "2026-08-29T20:00:00+03:00",
            "ended_at": "2026-08-29T20:10:00+03:00",
        },
        "classification": classification,
        "retry_count": 0,
        "start_state": "clean",
        "manual_repair": False,
        "stages": [
            {"stage": "requirements", "outcome": "passed"},
            {"stage": "schematic", "outcome": "passed"},
            {"stage": "erc", "outcome": "passed"},
            {"stage": "pcb", "outcome": "passed"},
            {"stage": "drc", "outcome": "passed"},
            {"stage": "parse_reopen", "outcome": "passed"},
        ],
        "validations": [
            {
                "kind": kind,
                "required": True,
                "execution_attempted": True,
                "execution_completed": True,
                "result_consumed": True,
                "disposition": "resolved",
            }
            for kind in ("erc", "drc")
        ],
        "mutations": [],
    }
    if classification != "success":
        categories = {
            "task_failure": "design",
            "provider_failure": "provider",
            "tool_failure": "tool",
        }
        payload["failure_category"] = categories[classification]
        payload["failure_reason_code"] = "fixture_failure"
    return payload


def _write_agent_log(path: Path, *, sequences: tuple[int, ...] = (1, 2)) -> None:
    events = []
    for index, sequence in enumerate(sequences):
        payload = _event_payload()
        payload["sequence"] = sequence
        payload["timestamp"] = f"2026-08-29T20:00:0{index}+03:00"
        events.append(json.dumps(payload, sort_keys=True))
    path.write_text("\n".join(events) + "\n", encoding="utf-8")


def _write_success_artifacts(attempt_dir: Path) -> None:
    for name in (
        "schematic.kicad_sch",
        "board.kicad_pcb",
        "ERC.txt",
        "DRC.txt",
        "BOM.csv",
        "manufacturing-report.md",
    ):
        (attempt_dir / name).write_text(f"fixture {name}\n", encoding="utf-8")
    gerbers = attempt_dir / "Gerbers"
    gerbers.mkdir()
    (gerbers / "board-F_Cu.gbr").write_text("G04 fixture*\n", encoding="utf-8")


def _write_bundle(tmp_path: Path, attempt_payload: dict[str, Any] | None = None) -> Path:
    root = tmp_path / "stm32-usbc-reference" / "v1"
    root.mkdir(parents=True)
    (root / "specification.md").write_text("# Fixture specification\n", encoding="utf-8")
    (root / "original-prompt.md").write_text("Create the fixture board.\n", encoding="utf-8")
    contract = evals.BenchmarkContract.model_validate(_benchmark_payload())
    (root / "benchmark.json").write_text(
        evals.render_benchmark_contract(contract), encoding="utf-8"
    )
    (root / "quality-gates.json").write_text(
        json.dumps(
            {
                "schema_version": "pcb-reference-board-quality.v1",
                "board_id": "stm32-usbc-reference",
                "benchmark_version": "v1",
                "rules": [{"id": "bom", "type": "artifact", "path": "BOM.csv", "kind": "file"}],
            }
        ),
        encoding="utf-8",
    )
    attempt_dir = root / "attempts" / "attempt-001"
    attempt_dir.mkdir(parents=True)
    record = evals.AttemptRecord.model_validate(attempt_payload or _attempt_payload())
    (attempt_dir / "attempt.json").write_text(evals.render_attempt_record(record), encoding="utf-8")
    _write_agent_log(attempt_dir / "agent-log.jsonl")
    _write_success_artifacts(attempt_dir)
    from kicad_mcp.evals.reference_board_quality import (
        render_quality_score,
        score_reference_board_attempt,
    )

    if record.attempt_id == attempt_dir.name:
        quality_score = score_reference_board_attempt(root, record.attempt_id)
        (attempt_dir / "board-quality-score.json").write_text(
            render_quality_score(quality_score), encoding="utf-8"
        )
    evidence_digest = evals.compute_attempt_evidence_digest(attempt_dir)
    reference_inputs_digest = evals.compute_reference_inputs_digest(root)
    manifest = evals.ReferenceBoardManifest.model_validate(
        _manifest_payload(evidence_digest, reference_inputs_digest)
    )
    (root / "attempt-manifest.json").write_text(
        json.dumps(manifest.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return root


def _refresh_attempt_evidence_digest(root: Path) -> None:
    manifest_path = root / "attempt-manifest.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    attempt_dir = root / "attempts" / "attempt-001"
    payload["attempts"][0]["evidence_digest"] = evals.compute_attempt_evidence_digest(attempt_dir)
    manifest_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def test_reference_bundle_rejects_unsafe_original_prompt_text(tmp_path: Path) -> None:
    root = _write_bundle(tmp_path)
    (root / "original-prompt.md").write_text(
        "Open /home/private/reference.kicad_pcb before editing.\n", encoding="utf-8"
    )

    with pytest.raises(evals.ReferenceCorpusError, match="original-prompt.md.*unsafe"):
        evals.validate_reference_board_bundle(root)


def test_reference_bundle_rejects_unsafe_success_artifact_text(tmp_path: Path) -> None:
    root = _write_bundle(tmp_path)
    report = root / "attempts" / "attempt-001" / "manufacturing-report.md"
    report.write_text("credential api_key=fixture-secret-value\n", encoding="utf-8")

    with pytest.raises(evals.ReferenceCorpusError, match="manufacturing-report.md.*unsafe"):
        evals.validate_reference_board_bundle(root)


def test_reference_bundle_validates_complete_attempt_denominator(tmp_path: Path) -> None:
    root = _write_bundle(tmp_path)

    result = evals.validate_reference_board_bundle(root)

    assert result.manifest.board_id == "stm32-usbc-reference"
    assert result.summary.attempts_total == 1
    assert result.summary.successful_attempts == 1


def test_reference_bundle_rejects_reference_input_digest_mismatch(tmp_path: Path) -> None:
    root = _write_bundle(tmp_path)
    (root / "specification.md").write_text(
        "# Changed but still safe fixture specification\n", encoding="utf-8"
    )

    with pytest.raises(evals.ReferenceCorpusError, match="reference input digest"):
        evals.validate_reference_board_bundle(root)


def test_reference_bundle_rejects_attempt_content_digest_mismatch(tmp_path: Path) -> None:
    root = _write_bundle(tmp_path)
    board = root / "attempts" / "attempt-001" / "board.kicad_pcb"
    board.write_text("stale replacement\n", encoding="utf-8")

    with pytest.raises(evals.ReferenceCorpusError, match="evidence digest"):
        evals.validate_reference_board_bundle(root)


def test_reference_bundle_rejects_unindexed_attempt_directory(tmp_path: Path) -> None:
    root = _write_bundle(tmp_path)
    (root / "attempts" / "attempt-undisclosed").mkdir()

    with pytest.raises(evals.ReferenceCorpusError, match="manifest.*filesystem"):
        evals.validate_reference_board_bundle(root)


def test_reference_bundle_rejects_manifest_benchmark_identity_mismatch(tmp_path: Path) -> None:
    root = _write_bundle(tmp_path)
    payload = json.loads((root / "attempt-manifest.json").read_text(encoding="utf-8"))
    payload["benchmark_version"] = "v2"
    (root / "attempt-manifest.json").write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(evals.ReferenceCorpusError, match="benchmark identity"):
        evals.validate_reference_board_bundle(root)


def test_reference_bundle_requires_validation_record_for_required_erc_drc(tmp_path: Path) -> None:
    payload = _attempt_payload(classification="tool_failure")
    payload["validations"] = []
    payload["stages"] = [{"stage": "requirements", "outcome": "passed"}]
    root = _write_bundle(tmp_path, payload)

    with pytest.raises(evals.ReferenceCorpusError, match="required erc.*validation evidence"):
        evals.validate_reference_board_bundle(root)


def test_reference_bundle_rejects_declared_success_that_fails_quality_gates(
    tmp_path: Path,
) -> None:
    payload = _attempt_payload()
    for stage in payload["stages"]:
        if stage["stage"] == "parse_reopen":
            stage["outcome"] = "failed"
    root = _write_bundle(tmp_path, payload)

    with pytest.raises(evals.ReferenceCorpusError, match="declared success.*quality gates"):
        evals.validate_reference_board_bundle(root)


def test_reference_bundle_rejects_success_with_manual_repair(tmp_path: Path) -> None:
    payload = _attempt_payload()
    payload["manual_repair"] = True
    root = _write_bundle(tmp_path, payload)

    with pytest.raises(evals.ReferenceCorpusError, match="manual repair"):
        evals.validate_reference_board_bundle(root)


def test_reference_bundle_rejects_success_missing_final_artifact(tmp_path: Path) -> None:
    root = _write_bundle(tmp_path)
    (root / "attempts" / "attempt-001" / "board.kicad_pcb").unlink()

    with pytest.raises(evals.ReferenceCorpusError, match="board.kicad_pcb"):
        evals.validate_reference_board_bundle(root)


def test_reference_bundle_rejects_success_with_empty_gerbers(tmp_path: Path) -> None:
    root = _write_bundle(tmp_path)
    (root / "attempts" / "attempt-001" / "Gerbers" / "board-F_Cu.gbr").unlink()

    with pytest.raises(evals.ReferenceCorpusError, match="Gerbers"):
        evals.validate_reference_board_bundle(root)


def test_reference_bundle_rejects_symlinked_publication_artifact(tmp_path: Path) -> None:
    root = _write_bundle(tmp_path)
    board = root / "attempts" / "attempt-001" / "board.kicad_pcb"
    target = root / "attempts" / "attempt-001" / "real-board.kicad_pcb"
    board.rename(target)
    board.symlink_to(target.name)

    with pytest.raises(evals.ReferenceCorpusError, match="symlink"):
        evals.validate_reference_board_bundle(root)


def test_reference_bundle_rejects_unsafe_attempt_json_value(tmp_path: Path) -> None:
    root = _write_bundle(tmp_path)
    attempt_path = root / "attempts" / "attempt-001" / "attempt.json"
    payload = json.loads(attempt_path.read_text(encoding="utf-8"))
    payload["toolchain_contract"] = "/home/private/toolchain-v1"
    attempt_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(evals.ReferenceCorpusError, match="attempt.json.*unsafe"):
        evals.validate_reference_board_bundle(root)


def test_reference_bundle_rejects_agent_log_attempt_identity_mismatch(
    tmp_path: Path,
) -> None:
    root = _write_bundle(tmp_path)
    log = root / "attempts" / "attempt-001" / "agent-log.jsonl"
    payload = _event_payload()
    payload["attempt_id"] = "attempt-002"
    log.write_text(json.dumps(payload) + "\n", encoding="utf-8")

    with pytest.raises(evals.ReferenceCorpusError, match="attempt identity"):
        evals.validate_reference_board_bundle(root)


def test_reference_bundle_rejects_noncontiguous_agent_log_sequence(tmp_path: Path) -> None:
    root = _write_bundle(tmp_path)
    log = root / "attempts" / "attempt-001" / "agent-log.jsonl"
    _write_agent_log(log, sequences=(1, 3))

    with pytest.raises(evals.ReferenceCorpusError, match="contiguous"):
        evals.validate_reference_board_bundle(root)


def test_reference_bundle_rejects_decreasing_agent_log_timestamp(tmp_path: Path) -> None:
    root = _write_bundle(tmp_path)
    log = root / "attempts" / "attempt-001" / "agent-log.jsonl"
    first = _event_payload()
    second = _event_payload()
    second["sequence"] = 2
    second["timestamp"] = "2026-08-29T19:59:59+03:00"
    log.write_text(
        json.dumps(first) + "\n" + json.dumps(second) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(evals.ReferenceCorpusError, match="nondecreasing"):
        evals.validate_reference_board_bundle(root)


def test_reference_bundle_rejects_malformed_agent_log_json(tmp_path: Path) -> None:
    root = _write_bundle(tmp_path)
    log = root / "attempts" / "attempt-001" / "agent-log.jsonl"
    log.write_text('{"sequence": 1\n', encoding="utf-8")

    with pytest.raises(evals.ReferenceCorpusError, match="invalid or unsafe"):
        evals.validate_reference_board_bundle(root)


def test_reference_bundle_rejects_agent_log_with_unsafe_value(tmp_path: Path) -> None:
    root = _write_bundle(tmp_path)
    log = root / "attempts" / "attempt-001" / "agent-log.jsonl"
    payload = _event_payload()
    payload["details"] = {"location": "/home/private/reference-board"}
    log.write_text(json.dumps(payload) + "\n", encoding="utf-8")

    with pytest.raises(evals.ReferenceCorpusError, match="agent log"):
        evals.validate_reference_board_bundle(root)


def test_attempt_evidence_digest_rejects_non_directory_root(tmp_path: Path) -> None:
    with pytest.raises(evals.ReferenceCorpusError, match="real directory"):
        evals.compute_attempt_evidence_digest(tmp_path / "missing-attempt")


def test_attempt_evidence_digest_rejects_symlinked_tree_entry(tmp_path: Path) -> None:
    attempt_dir = tmp_path / "attempt"
    attempt_dir.mkdir()
    target = attempt_dir / "target.txt"
    target.write_text("fixture\n", encoding="utf-8")
    (attempt_dir / "alias.txt").symlink_to(target.name)

    with pytest.raises(evals.ReferenceCorpusError, match="must not contain symlinks"):
        evals.compute_attempt_evidence_digest(attempt_dir)


def test_reference_bundle_rejects_non_object_manifest_json(tmp_path: Path) -> None:
    root = _write_bundle(tmp_path)
    (root / "attempt-manifest.json").write_text("[]\n", encoding="utf-8")

    with pytest.raises(evals.ReferenceCorpusError, match="must contain one JSON object"):
        evals.validate_reference_board_bundle(root)


def test_reference_bundle_rejects_invalid_utf8_public_text(tmp_path: Path) -> None:
    root = _write_bundle(tmp_path)
    (root / "original-prompt.md").write_bytes(b"\xff\xfe\xfd")

    with pytest.raises(evals.ReferenceCorpusError, match="readable UTF-8 text"):
        evals.validate_reference_board_bundle(root)


def test_reference_bundle_rejects_empty_agent_log(tmp_path: Path) -> None:
    root = _write_bundle(tmp_path)
    log = root / "attempts" / "attempt-001" / "agent-log.jsonl"
    log.write_text("", encoding="utf-8")

    with pytest.raises(evals.ReferenceCorpusError, match="at least one event"):
        evals.validate_reference_board_bundle(root)


def test_reference_bundle_rejects_blank_agent_log_event(tmp_path: Path) -> None:
    root = _write_bundle(tmp_path)
    log = root / "attempts" / "attempt-001" / "agent-log.jsonl"
    log.write_text("\n", encoding="utf-8")

    with pytest.raises(evals.ReferenceCorpusError, match="blank events"):
        evals.validate_reference_board_bundle(root)


def test_reference_bundle_rejects_missing_gerbers_directory(tmp_path: Path) -> None:
    root = _write_bundle(tmp_path)
    gerbers = root / "attempts" / "attempt-001" / "Gerbers"
    for entry in gerbers.iterdir():
        entry.unlink()
    gerbers.rmdir()

    with pytest.raises(evals.ReferenceCorpusError, match="Gerbers directory is required"):
        evals.validate_reference_board_bundle(root)


def test_reference_bundle_rejects_symlinked_gerbers_directory(tmp_path: Path) -> None:
    root = _write_bundle(tmp_path)
    attempt_dir = root / "attempts" / "attempt-001"
    gerbers = attempt_dir / "Gerbers"
    target = attempt_dir / "real-gerbers"
    gerbers.rename(target)
    gerbers.symlink_to(target.name, target_is_directory=True)

    with pytest.raises(evals.ReferenceCorpusError, match="Gerbers must not be a symlink"):
        evals.validate_reference_board_bundle(root)


def test_reference_bundle_rejects_invalid_attempt_contract(tmp_path: Path) -> None:
    root = _write_bundle(tmp_path)
    attempt_path = root / "attempts" / "attempt-001" / "attempt.json"
    payload = json.loads(attempt_path.read_text(encoding="utf-8"))
    payload.pop("source_revision")
    attempt_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(evals.ReferenceCorpusError, match="violates pcb-task-outcome.v1"):
        evals.validate_reference_board_bundle(root)


def test_reference_bundle_rejects_non_directory_root(tmp_path: Path) -> None:
    with pytest.raises(evals.ReferenceCorpusError, match="must be a directory"):
        evals.validate_reference_board_bundle(tmp_path / "missing-bundle")


def test_reference_bundle_rejects_attempt_identity_mismatch(tmp_path: Path) -> None:
    root = _write_bundle(tmp_path, _attempt_payload(attempt_id="attempt-002"))

    with pytest.raises(evals.ReferenceCorpusError, match="attempt id does not match"):
        evals.validate_reference_board_bundle(root)


def test_reference_bundle_rejects_attempt_benchmark_identity_mismatch(tmp_path: Path) -> None:
    payload = _attempt_payload()
    payload["benchmark_version"] = "v2"
    root = _write_bundle(tmp_path, payload)

    with pytest.raises(evals.ReferenceCorpusError, match="attempt benchmark identity"):
        evals.validate_reference_board_bundle(root)


ROOT = Path(__file__).resolve().parents[2]
VALIDATOR_SCRIPT = ROOT / "scripts" / "validate_reference_board_bundle.py"


def _load_validator_script() -> ModuleType:
    if not VALIDATOR_SCRIPT.is_file():
        pytest.fail("reference-board validator script is missing")
    spec = importlib.util.spec_from_file_location(
        "validate_reference_board_bundle", VALIDATOR_SCRIPT
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_reference_bundle_cli_prints_bounded_success_summary(tmp_path: Path, capsys) -> None:
    root = _write_bundle(tmp_path)
    module = _load_validator_script()

    result = module.main(["--bundle", str(root)])

    captured = capsys.readouterr()
    assert result == 0
    assert "board=stm32-usbc-reference" in captured.out
    assert "attempts=1" in captured.out
    assert "successful=1" in captured.out
    assert "fixture-provider" not in captured.out
    assert captured.err == ""


def test_reference_bundle_cli_fails_closed_without_dumping_agent_log(
    tmp_path: Path, capsys
) -> None:
    root = _write_bundle(tmp_path)
    (root / "attempts" / "attempt-undisclosed").mkdir()
    log_text = (root / "attempts" / "attempt-001" / "agent-log.jsonl").read_text(encoding="utf-8")
    module = _load_validator_script()

    result = module.main(["--bundle", str(root)])

    captured = capsys.readouterr()
    assert result != 0
    assert "reference corpus validation failed" in captured.err
    assert log_text not in captured.err
    assert captured.out == ""


def test_reference_bundle_success_requires_quality_score(tmp_path: Path) -> None:
    root = _write_bundle(tmp_path)
    score = root / "attempts" / "attempt-001" / "board-quality-score.json"
    score.unlink()
    _refresh_attempt_evidence_digest(root)

    with pytest.raises(evals.ReferenceCorpusError, match="board-quality-score.json"):
        evals.validate_reference_board_bundle(root)


def test_reference_bundle_success_requires_passing_quality_score(tmp_path: Path) -> None:
    root = _write_bundle(tmp_path)
    score = root / "attempts" / "attempt-001" / "board-quality-score.json"
    payload = json.loads(score.read_text(encoding="utf-8"))
    payload["passed_required_rule_count"] = 0
    payload["quality_score_percent"] = 0.0
    payload["overall_pass"] = False
    payload["results"][0]["status"] = "fail"
    payload["results"][0]["reason_code"] = "artifact_missing"
    score.write_text(json.dumps(payload), encoding="utf-8")
    _refresh_attempt_evidence_digest(root)

    with pytest.raises(evals.ReferenceCorpusError, match="quality score.*pass"):
        evals.validate_reference_board_bundle(root)


def test_reference_bundle_quality_gate_contract_is_reference_input(tmp_path: Path) -> None:
    root = _write_bundle(tmp_path)
    quality_path = root / "quality-gates.json"
    payload = json.loads(quality_path.read_text(encoding="utf-8"))
    payload["rules"][0]["path"] = "manufacturing-report.md"
    quality_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(evals.ReferenceCorpusError, match="reference input digest"):
        evals.validate_reference_board_bundle(root)


def test_reference_bundle_rejects_forged_passing_quality_report(tmp_path: Path) -> None:
    root = _write_bundle(tmp_path)
    quality_path = root / "quality-gates.json"
    quality = json.loads(quality_path.read_text(encoding="utf-8"))
    quality["rules"][0]["path"] = "missing-quality-proof.txt"
    quality_path.write_text(json.dumps(quality), encoding="utf-8")

    manifest_path = root / "attempt-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["reference_inputs_digest"] = evals.compute_reference_inputs_digest(root)
    attempt_dir = root / "attempts" / "attempt-001"
    manifest["attempts"][0]["evidence_digest"] = evals.compute_attempt_evidence_digest(attempt_dir)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(evals.ReferenceCorpusError, match="deterministic scorer"):
        evals.validate_reference_board_bundle(root)

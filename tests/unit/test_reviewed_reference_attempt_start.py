"""Explicit, non-retry reference schematic execution with private receipts."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import start_reviewed_reference_attempt as cli


def _fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    board_dir = tmp_path / "docs/evidence/reference-boards/esp32-c6-usbc/v1"
    board_dir.mkdir(parents=True)
    (board_dir / "original-prompt.md").write_text("# fixture prompt\n", encoding="utf-8")
    monkeypatch.setattr(
        cli,
        "preflight",
        lambda **_: {
            "status": "ready",
            "source_revision": "a" * 40,
            "reviewed_input_sha256": {"original-prompt.md": "b" * 64},
            "blocking_reasons": [],
        },
    )
    return tmp_path


def _invoke(tmp_path: Path, *, execute: bool, acknowledged: bool, runner):
    return cli.start_reviewed_attempt(
        root=tmp_path,
        board_id="esp32-c6-usbc",
        attempt_number=17,
        execute=execute,
        cost_acknowledged=acknowledged,
        runner=runner,
    )


def _receipt(tmp_path: Path) -> Path:
    return (
        tmp_path
        / ".dev-tools/reference-agent-runs/esp32-c6-usbc/v1/attempt-017"
        / "schematic-execution-receipt.json"
    )


def test_default_preview_has_no_cost_reservation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fixture(tmp_path, monkeypatch)
    touched: list[str] = []
    result = _invoke(
        tmp_path, execute=False, acknowledged=True, runner=lambda _: touched.append("run")
    )
    assert result["status"] == "ready_for_explicit_execution"
    assert not touched
    assert not _receipt(tmp_path).exists()
    assert result["counts_as_task_success"] is False


def test_execute_without_explicit_provider_cost_acknowledgement_blocks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fixture(tmp_path, monkeypatch)
    result = _invoke(
        tmp_path, execute=True, acknowledged=False, runner=lambda _: pytest.fail("executed")
    )
    assert result["reason_codes"] == ["operator_cost_acknowledgement_required"]
    assert not _receipt(tmp_path).exists()


def test_preflight_failure_blocks_before_any_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(
        cli,
        "preflight",
        lambda **_: {"status": "blocked", "blocking_reasons": ["reviewed_agent_cli_unavailable"]},
    )
    result = _invoke(
        tmp_path, execute=True, acknowledged=True, runner=lambda _: pytest.fail("executed")
    )
    assert result["reason_codes"] == ["reviewed_agent_cli_unavailable"]
    assert not _receipt(tmp_path).exists()


def test_failed_runner_never_disappears_from_private_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fixture(tmp_path, monkeypatch)
    seen: list[list[str]] = []

    def fail(argv: list[str]) -> int:
        seen.append(argv)
        print("private runner output must be redacted")
        return 1

    outcome = _invoke(tmp_path, execute=True, acknowledged=True, runner=fail)
    assert outcome["status"] == "phase_failed_needs_evidence_review"
    assert seen == [
        ["--board-id", "esp32-c6-usbc", "--attempt-number", "17", "--phase", "schematic"]
    ]
    saved = json.loads(_receipt(tmp_path).read_text(encoding="utf-8"))
    assert saved["state"] == "executor_failed"
    assert saved["source_revision"] == "a" * 40
    assert saved["reviewed_input_sha256"]["original-prompt.md"] == "b" * 64
    assert saved["counts_as_task_success"] is False
    assert "private" not in json.dumps(saved) + json.dumps(outcome)
    assert _invoke(tmp_path, execute=True, acknowledged=True, runner=fail)["reason_codes"] == [
        "attempt_identity_already_used"
    ]
    assert len(seen) == 1


def test_exception_does_not_leak_secrets(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _fixture(tmp_path, monkeypatch)

    def raise_secret(_: list[str]) -> int:
        raise RuntimeError("sk-api-key-not-for-publication")

    result = _invoke(tmp_path, execute=True, acknowledged=True, runner=raise_secret)
    assert result["status"] == "phase_failed_needs_evidence_review"
    assert "sk-api-key" not in json.dumps(result) + _receipt(tmp_path).read_text()


def test_exit_zero_with_missing_or_corrupt_agent_log_is_not_accepted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fixture(tmp_path, monkeypatch)
    result = _invoke(tmp_path, execute=True, acknowledged=True, runner=lambda _: 0)
    assert result["status"] == "phase_failed_needs_evidence_review"
    assert json.loads(_receipt(tmp_path).read_text())["state"] == "executor_failed"


def test_valid_sanitized_agent_log_only_marks_phase_as_requiring_review(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fixture(tmp_path, monkeypatch)

    def simulated_runner(_: list[str]) -> int:
        path = (
            tmp_path
            / "docs/evidence/reference-boards/esp32-c6-usbc/v1/attempts/attempt-017"
            / "agent-log.jsonl"
        )
        path.parent.mkdir(parents=True)
        path.write_text(
            json.dumps(
                {
                    "schema_version": "pcb-reference-agent-log.v1",
                    "attempt_id": "attempt-017",
                    "sequence": 1,
                    "timestamp": "2026-10-11T17:00:00Z",
                    "event_type": "workflow",
                    "name": "claude_session",
                    "status": "completed",
                    "details": {},
                }
            )
            + "\n",
            encoding="utf-8",
        )
        return 0

    result = _invoke(tmp_path, execute=True, acknowledged=True, runner=simulated_runner)
    assert result["status"] == "phase_finished_needs_evidence_review"
    assert result["counts_as_task_success"] is False
    assert result["published_attempt_record"] is False
    assert (
        json.loads(_receipt(tmp_path).read_text())["state"] == "executor_returned_success_with_log"
    )


def test_symlinked_scratch_parent_blocks_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fixture(tmp_path, monkeypatch)
    external = tmp_path / "external"
    external.mkdir()
    (tmp_path / ".dev-tools").symlink_to(external, target_is_directory=True)
    result = _invoke(
        tmp_path, execute=True, acknowledged=True, runner=lambda _: pytest.fail("executed")
    )
    assert result["reason_codes"] == ["unsafe_scratch_path"]
    assert not (external / "reference-agent-runs").exists()


def test_existing_scratch_reservation_is_never_reused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fixture(tmp_path, monkeypatch)
    scratch = _receipt(tmp_path).parent
    scratch.mkdir(parents=True)
    result = _invoke(
        tmp_path, execute=True, acknowledged=True, runner=lambda _: pytest.fail("executed")
    )
    assert result["reason_codes"] == ["attempt_identity_already_used"]


def test_cli_without_real_agent_stays_safely_blocked(
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = cli.main(["--board-id", "rp2350-usbc", "--attempt-number", "912"])
    output = json.loads(capsys.readouterr().out)
    assert result in (0, 2)
    assert output["counts_as_task_success"] is False
    assert output["published_attempt_record"] is False
    assert output["status"] in {"blocked", "ready_for_explicit_execution"}

"""Reproducible, no-cherry-picking reference-board task outcome scoreboard."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from scripts import report_reference_board_attempts as scoreboard

ROOT = Path(__file__).resolve().parents[2]
CORPUS = ROOT / "docs/evidence/reference-boards"
STM = CORPUS / "stm32f072-usbc/v1"


def test_real_reference_corpus_lists_all_boards_and_all_three_attempts() -> None:
    report = scoreboard.audit_corpus(CORPUS)
    assert report["schema_version"] == scoreboard.SCHEMA
    assert report["status"] == "incomplete"
    assert report["summary"] == {
        "board_versions_total": 3,
        "validated_versions": 1,
        "incomplete_versions": 2,
        "cross_benchmark_success_rate": None,
        "cross_benchmark_kpi_publishable": False,
    }
    boards = {item["board_id"]: item for item in report["board_versions"]}
    assert set(boards) == {"esp32-c6-usbc", "stm32f072-usbc", "rp2350-usbc"}
    assert boards["esp32-c6-usbc"]["status"] == "incomplete"
    assert boards["rp2350-usbc"]["status"] == "incomplete"
    stm = boards["stm32f072-usbc"]
    assert stm["status"] == "validated"
    assert (
        stm["attempts_total"],
        stm["valid_attempts"],
        stm["failed_attempts"],
        stm["infrastructure_invalid_attempts"],
    ) == (3, 2, 2, 1)
    assert stm["successful_attempts"] == 0
    assert stm["task_success"]["denominator"] == 2
    assert stm["task_success"]["numerator"] == 0
    assert stm["classifications"] == {"provider_failure": 2, "infrastructure_invalid": 1}
    assert [item["attempt_id"] for item in stm["attempt_history"]] == [
        "attempt-001",
        "attempt-002",
        "attempt-003",
    ]
    assert [item["classification"] for item in stm["attempt_history"]] == [
        "provider_failure",
        "infrastructure_invalid",
        "provider_failure",
    ]
    assert all(item["quality"]["all_rules_passed"] is False for item in stm["attempt_history"])
    assert all(item["quality"]["score_percent"] == 0 for item in stm["attempt_history"])


def test_single_validated_board_report_has_canonical_nonfabricated_kpis(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert scoreboard.main(["--bundle", str(STM)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "validated"
    board = report["board_version"]
    assert board["benchmark_id"] == "stm32f072-usbc-reference-board"
    assert board["task_success"]["status"] == "not_met"
    assert board["required_drc_execution"]["denominator"] == 2
    assert board["manufacturing_reproducibility"]["denominator"] == 2
    assert len(board["reference_inputs_digest"]) == 71
    assert "/home/" not in json.dumps(report)


def test_partial_corpus_returns_two_and_never_reports_global_success(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert scoreboard.main(["--corpus-root", str(CORPUS)]) == 2
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "incomplete"
    assert report["summary"]["cross_benchmark_kpi_publishable"] is False
    assert report["summary"]["cross_benchmark_success_rate"] is None


def test_input_manifest_tampering_cannot_hide_failed_attempt(tmp_path: Path) -> None:
    board = tmp_path / "stm32f072-usbc/v1"
    shutil.copytree(STM, board)
    manifest = board / "attempt-manifest.json"
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["attempts"] = [payload["attempts"][0]]
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    report = scoreboard.audit_bundle(board)
    assert report["status"] == "incomplete"
    assert "attempt_history" not in report["board_version"]
    assert "task_success" not in report["board_version"]


def test_digest_mismatch_fails_closed_without_leaking_input(tmp_path: Path) -> None:
    board = tmp_path / "stm32f072-usbc/v1"
    shutil.copytree(STM, board)
    attempt = board / "attempts/attempt-003/attempt.json"
    payload = json.loads(attempt.read_text(encoding="utf-8"))
    payload["provider"] = "private-provider"
    attempt.write_text(json.dumps(payload), encoding="utf-8")
    report = scoreboard.audit_bundle(board)
    assert report["status"] == "incomplete"
    assert "private-provider" not in json.dumps(report)
    assert str(tmp_path) not in json.dumps(report)


def test_unindexed_attempt_directory_is_not_dropped(tmp_path: Path) -> None:
    board = tmp_path / "stm32f072-usbc/v1"
    shutil.copytree(STM, board)
    (board / "attempts/attempt-999").mkdir()
    assert scoreboard.audit_bundle(board)["status"] == "incomplete"


def test_rejects_symlink_board_and_invalid_corpus_entries(tmp_path: Path) -> None:
    root = tmp_path / "corpus"
    root.mkdir()
    (root / "README.md").write_text("# reviewed\n", encoding="utf-8")
    (root / "a-board").symlink_to(STM.parent, target_is_directory=True)
    report = scoreboard.audit_corpus(root)
    assert report["status"] == "invalid_corpus"
    assert report["reason_code"] == "unsupported_corpus_entry"
    assert str(STM) not in json.dumps(report)
    (root / "a-board").unlink()
    (root / "a-board").mkdir()
    (root / "a-board/sneaky.txt").write_text("unindexed input")
    assert scoreboard.audit_corpus(root)["status"] == "invalid_corpus"
    (root / "a-board/sneaky.txt").unlink()
    assert scoreboard.audit_corpus(root)["status"] == "incomplete"
    assert (
        scoreboard.audit_corpus(root)["board_versions"][0]["reason_code"] == "no_benchmark_versions"
    )


def test_missing_root_or_malformed_bundle_has_bounded_failure_codes(tmp_path: Path) -> None:
    assert scoreboard.audit_corpus(tmp_path / "missing")["reason_code"] == "invalid_corpus_root"
    assert (
        scoreboard.audit_bundle(tmp_path / "invalid-board/version")["reason_code"]
        == "invalid_bundle_identity"
    )


def test_repeated_report_is_byte_deterministic() -> None:
    first = json.dumps(scoreboard.audit_corpus(CORPUS), sort_keys=True)
    second = json.dumps(scoreboard.audit_corpus(CORPUS), sort_keys=True)
    assert first == second
    assert "provider_rate_limit" in first
    assert "provider_api_error" in first


def test_recomputed_score_identity_mismatch_invalidates_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real = scoreboard.score_reference_board_attempt

    def wrong_version(root: Path, attempt_id: str):
        original = real(root, attempt_id)
        return original.model_copy(update={"benchmark_version": "v42"})

    monkeypatch.setattr(scoreboard, "score_reference_board_attempt", wrong_version)
    result = scoreboard.audit_bundle(STM)
    assert result["status"] == "incomplete"
    assert "attempt_history" not in result["board_version"]


def test_empty_corpus_is_not_a_success(tmp_path: Path) -> None:
    report = scoreboard.audit_corpus(tmp_path)
    assert report["status"] == "incomplete"
    assert report["summary"]["board_versions_total"] == 0
    assert report["summary"]["cross_benchmark_success_rate"] is None


def test_unexpected_file_in_corpus_root_fails_closed(tmp_path: Path) -> None:
    (tmp_path / "unexpected-source.txt").write_text("not an allowed evidence tree")
    result = scoreboard.audit_corpus(tmp_path)
    assert result["status"] == "invalid_corpus"
    assert result["reason_code"] == "unsupported_corpus_entry"
    assert "not an allowed evidence tree" not in json.dumps(result)


def test_unicode_version_identifier_remains_invalid(tmp_path: Path) -> None:
    board = tmp_path / "stm32f072-usbc"
    board.mkdir()
    (board / "v١").mkdir()
    report = scoreboard.audit_corpus(tmp_path)
    assert report["status"] == "invalid_corpus"
    assert report["reason_code"] == "unsupported_corpus_entry"
    assert "board_versions" not in report

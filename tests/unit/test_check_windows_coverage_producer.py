"""Exercise the current-attempt producer evidence before polling again."""

from __future__ import annotations

import io
import json
import sys
from typing import Any

import pytest

from scripts import check_windows_coverage_producer as producer

RUN_ID = 45320850286
SHA = "6a6a276f62c9c3d55be68c6b6f6ee558fb6d8b73"
UPLOAD = "Upload exact-run native Windows coverage"


def _job(
    *,
    status: str = "completed",
    conclusion: str | None = "failure",
    upload: str | None = "skipped",
) -> dict[str, Any]:
    return {
        "name": "mcp-server (windows-2025)",
        "run_id": RUN_ID,
        "run_attempt": 1,
        "head_sha": SHA,
        "status": status,
        "conclusion": conclusion,
        "steps": [{"name": UPLOAD, "status": "completed", "conclusion": upload}]
        if upload is not None
        else [],
    }


def _check(jobs: list[dict[str, Any]], *, total_count: int | None = None) -> None:
    producer.check_producer(
        {"total_count": len(jobs) if total_count is None else total_count, "jobs": jobs},
        run_id=RUN_ID,
        attempt=1,
        head=SHA,
    )


@pytest.mark.parametrize("conclusion", ["failure", "cancelled", "skipped", "timed_out"])
def test_terminal_producer_with_impossible_upload_fails_promptly(conclusion: str) -> None:
    with pytest.raises(ValueError, match="cannot produce"):
        _check([_job(conclusion=conclusion)])


def test_cancelled_before_upload_has_no_possible_artifact() -> None:
    with pytest.raises(ValueError, match="cannot produce"):
        _check([_job(conclusion="cancelled", upload=None)])


@pytest.mark.parametrize("conclusion", ["success", "failure"])
def test_successful_upload_can_still_await_artifact_visibility(conclusion: str) -> None:
    _check([_job(conclusion=conclusion, upload="success")])


def test_active_and_missing_producer_keep_bounded_wait() -> None:
    _check([_job(status="in_progress", conclusion=None, upload=None)])
    _check([])


def test_completed_success_with_skipped_upload_fails() -> None:
    with pytest.raises(ValueError, match="cannot produce"):
        _check([_job(conclusion="success", upload="skipped")])


@pytest.mark.parametrize(
    ("field", "value"),
    [("run_attempt", 2), ("run_id", 1), ("head_sha", "0" * 40)],
)
def test_foreign_attempt_or_head_is_not_accepted(field: str, value: object) -> None:
    with pytest.raises(ValueError, match="identity mismatch"):
        _check([_job() | {field: value}])


def test_ambiguous_job_listing_fails_closed() -> None:
    with pytest.raises(ValueError, match="Ambiguous Windows coverage producer"):
        _check([_job(), _job()])


def test_incomplete_job_listing_fails_closed() -> None:
    with pytest.raises(ValueError, match="Incomplete workflow job listing"):
        _check([_job()], total_count=2)


def test_ambiguous_upload_steps_fail_closed() -> None:
    job = _job()
    job["steps"] *= 2
    with pytest.raises(ValueError, match="Ambiguous Windows coverage upload step"):
        _check([job])


@pytest.mark.parametrize("payload", [None, {"jobs": None}, {"jobs": [None]}])
def test_invalid_job_evidence_fails_closed(payload: object) -> None:
    with pytest.raises(ValueError, match="Invalid workflow job"):
        producer.check_producer(payload, run_id=RUN_ID, attempt=1, head=SHA)


@pytest.mark.parametrize("upload", ["success", "skipped"])
def test_cli_reports_producer_result(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], upload: str
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "check_windows_coverage_producer.py",
            "--run-id",
            str(RUN_ID),
            "--attempt",
            "1",
            "--head",
            SHA,
        ],
    )
    monkeypatch.setattr(
        sys,
        "stdin",
        io.StringIO(json.dumps({"total_count": 1, "jobs": [_job(upload=upload)]})),
    )
    if upload == "success":
        assert producer.main() == 0
    else:
        with pytest.raises(SystemExit) as exc:
            producer.main()
        assert exc.value.code == 1
        assert "::error::Windows producer cannot produce coverage" in capsys.readouterr().err

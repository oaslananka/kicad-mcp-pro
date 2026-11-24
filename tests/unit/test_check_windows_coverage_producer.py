"""Exercise the current-attempt producer evidence before polling again."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
RUN_ID = 45320850286
SHA = "6a6a276f62c9c3d55be68c6b6f6ee558fb6d8b73"
UPLOAD = "Upload exact-run native Windows coverage"


def _job(
    *,
    status: str = "completed",
    conclusion: str | None = "failure",
    upload: str | None = "skipped",
) -> dict:
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


def _check(jobs: list[dict], *, total_count: int | None = None) -> subprocess.CompletedProcess[str]:
    payload = {"total_count": len(jobs) if total_count is None else total_count, "jobs": jobs}
    return subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/check_windows_coverage_producer.py"),
            "--run-id",
            str(RUN_ID),
            "--attempt",
            "1",
            "--head",
            SHA,
        ],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )


@pytest.mark.parametrize("conclusion", ["failure", "cancelled", "skipped", "timed_out"])
def test_terminal_producer_with_impossible_upload_fails_promptly(conclusion: str) -> None:
    result = _check([_job(conclusion=conclusion)])
    assert result.returncode == 1
    assert "cannot produce" in result.stderr


def test_cancelled_before_upload_has_no_possible_artifact() -> None:
    result = _check([_job(conclusion="cancelled", upload=None)])
    assert result.returncode == 1
    assert "cannot produce" in result.stderr


def test_successful_upload_can_still_await_artifact_visibility() -> None:
    for conclusion in ("success", "failure"):
        assert _check([_job(conclusion=conclusion, upload="success")]).returncode == 0


def test_active_and_missing_producer_keep_bounded_wait() -> None:
    assert _check([_job(status="in_progress", conclusion=None, upload=None)]).returncode == 0
    assert _check([]).returncode == 0


def test_completed_success_with_skipped_upload_fails() -> None:
    result = _check([_job(conclusion="success", upload="skipped")])
    assert result.returncode == 1
    assert "cannot produce" in result.stderr


@pytest.mark.parametrize(
    ("field", "value"),
    [("run_attempt", 2), ("run_id", 1), ("head_sha", "0" * 40)],
)
def test_foreign_attempt_or_head_is_not_accepted(field: str, value: object) -> None:
    result = _check([_job() | {field: value}])
    assert result.returncode == 1
    assert "identity" in result.stderr


def test_ambiguous_or_incomplete_job_listing_fails_closed() -> None:
    assert _check([_job(), _job()]).returncode == 1
    assert _check([_job()], total_count=2).returncode == 1


def test_ambiguous_upload_steps_fail_closed() -> None:
    job = _job()
    job["steps"] *= 2
    assert _check([job]).returncode == 1


@pytest.mark.skipif(
    sys.platform == "win32" or not shutil.which("bash") or not shutil.which("jq"),
    reason="The coverage wait step runs in Ubuntu Bash with jq.",
)
@pytest.mark.parametrize(
    ("job_exit", "upload", "expected_exit", "waits"),
    [(0, "skipped", 1, False), (0, "success", 0, True), (1, "success", 1, False)],
)
def test_actual_workflow_polling_step(
    tmp_path: Path, job_exit: int, upload: str, expected_exit: int, waits: bool
) -> None:
    workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text("utf-8"))
    step = next(
        s for s in workflow["jobs"]["coverage"]["steps"] if s.get("id") == "native-windows-coverage"
    )
    output = tmp_path / "output"
    trace = tmp_path / "trace"
    output.touch()
    job = _job(upload=upload)
    harness = """
gh() {
    if [[ "$1" != api ]]; then return 99; fi
    case "$2" in
        "repos/$GITHUB_REPOSITORY/actions/runs/$GITHUB_RUN_ID/artifacts?per_page=100")
            if [[ -f "$TRACE_FILE" ]]; then
                printf '%s' "$MOCK_ARTIFACT"
            else
                printf '%s' '{"artifacts":[]}'
            fi
            ;;
        "repos/$GITHUB_REPOSITORY/actions/runs/$GITHUB_RUN_ID/attempts/$GITHUB_RUN_ATTEMPT/jobs?per_page=100")
            if [[ "$MOCK_JOB_EXIT" != 0 ]]; then return 1; fi
            printf '%s' "$MOCK_JOBS"
            ;;
        *) return 99 ;;
    esac
}
sleep() { printf 'wait
' >> "$TRACE_FILE"; }
"""
    name = f"windows-python-coverage-{RUN_ID}-1"
    bash = shutil.which("bash")
    assert bash is not None
    result = subprocess.run(
        [bash, "-c", harness + step["run"]],
        cwd=ROOT,
        env={
            **os.environ,
            "GITHUB_REPOSITORY": "test/repo",
            "GITHUB_RUN_ID": str(RUN_ID),
            "GITHUB_RUN_ATTEMPT": "1",
            "COVERAGE_ARTIFACT": name,
            "COVERAGE_PRODUCER_HEAD": SHA,
            "GITHUB_OUTPUT": str(output),
            "TRACE_FILE": str(trace),
            "MOCK_JOB_EXIT": str(job_exit),
            "MOCK_JOBS": json.dumps({"total_count": 1, "jobs": [job]}),
            "MOCK_ARTIFACT": json.dumps(
                {"artifacts": [{"id": 14889028259, "name": name, "expired": False}]}
            ),
        },
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == expected_exit
    assert trace.exists() == waits
    if waits:
        assert trace.read_text("utf-8") == "wait\n"
        assert output.read_text("utf-8") == "artifact_id=14889028259\n"
    else:
        assert output.read_text("utf-8") == ""

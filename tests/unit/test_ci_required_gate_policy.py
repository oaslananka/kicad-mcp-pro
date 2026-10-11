"""Execute the actual Required PR Gate shell policy for expected/unsafe skip cases."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
JOB_RESULTS = (
    "changes",
    "release-metadata",
    "python-changed-quality",
    "mcp-server",
    "coverage",
    "mcp-npm",
    "chatgpt-app",
    "protocol-schemas",
    "mcp-2026-compat",
    "workflow-policy",
    "security",
    "release-readiness",
)


def _run_gate(
    tmp_path: Path,
    *,
    event: str = "pull_request",
    head_ref: str = "topic",
    overrides: dict[str, str] | None = None,
) -> tuple[int, str]:
    workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())
    run = next(
        step["run"]
        for step in workflow["jobs"]["required-pr-gate"]["steps"]
        if step.get("name") == "Evaluate required job results"
    )
    results = {job: "success" for job in JOB_RESULTS}
    results["release-readiness"] = (
        "skipped" if head_ref != "release-please--branches--main" else "success"
    )
    if event == "workflow_dispatch":
        results["changes"] = "skipped"
    results.update(overrides or {})
    for job, outcome in results.items():
        run = run.replace("${{ needs." + job + ".result }}", outcome)
    run = re.sub(
        r"\$\{\{ needs\.changes\.outputs\.(?:docs_only|release_metadata_only) \}\}", "false", run
    )
    assert "${{" not in run
    summary = tmp_path / "gate-summary.md"
    summary.touch()
    completed = subprocess.run(
        ["/bin/bash", "-eu", "-o", "pipefail", "-c", run],
        cwd=ROOT,
        env={
            "PATH": "/usr/bin:/bin",
            "GITHUB_STEP_SUMMARY": str(summary),
            "GITHUB_EVENT_NAME": event,
            "GITHUB_HEAD_REF": head_ref,
        },
        capture_output=True,
        text=True,
        timeout=12,
    )
    return completed.returncode, summary.read_text()


@pytest.mark.parametrize(
    ("event", "head_ref", "overrides", "should_pass"),
    [
        ("pull_request", "topic", {}, True),
        ("pull_request", "release-please--branches--main", {}, True),
        ("workflow_dispatch", "", {}, True),
        ("push", "", {}, True),
        ("pull_request", "topic", {"coverage": "skipped"}, False),
        ("pull_request", "topic", {"mcp-server": "skipped"}, False),
        ("pull_request", "topic", {"security": "skipped"}, False),
        ("pull_request", "release-please--branches--main", {"release-readiness": "skipped"}, False),
        ("pull_request", "topic", {"changes": "skipped"}, False),
        ("pull_request", "topic", {"coverage": "failure"}, False),
        ("pull_request", "topic", {"coverage": "cancelled"}, False),
        ("pull_request", "topic", {"coverage": "unknown"}, False),
        ("push", "", {"release-metadata": "skipped"}, False),
    ],
)
def test_required_gate_rejects_unexpected_skips(
    tmp_path: Path,
    event: str,
    head_ref: str,
    overrides: dict[str, str],
    should_pass: bool,
) -> None:
    exit_code, summary = _run_gate(tmp_path, event=event, head_ref=head_ref, overrides=overrides)
    assert (exit_code == 0) is should_pass
    assert "Explanation" in summary
    if not should_pass:
        assert "❌" in summary


def test_main_and_pr_concurrency_are_isolated() -> None:
    workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())
    group = workflow["concurrency"]["group"]
    cancel = workflow["concurrency"]["cancel-in-progress"]
    assert "github.sha" in group and "github.ref" in group
    assert "github.event_name == 'push'" in group
    assert "github.event_name != 'push'" in cancel

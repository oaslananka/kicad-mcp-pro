"""Static and parameterized guardrails for the inline required PR Bash gate.

The inline gate is intentionally kept in the trusted workflow instead of
executing a repository-controlled Python policy script with a PR checkout.
"""

from __future__ import annotations

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


def _required_gate() -> str:
    workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"))
    return next(
        step["run"]
        for step in workflow["jobs"]["required-pr-gate"]["steps"]
        if step.get("name") == "Evaluate required job results"
    )


@pytest.mark.parametrize("job", JOB_RESULTS)
def test_each_required_job_is_covered_by_explicit_policy(job: str) -> None:
    gate = _required_gate()
    assert f'[{job}]="${{{{ needs.{job}.result }}}}"' in gate
    assert job in gate.split("for job in ", 1)[1].split("; do", 1)[0].split()


def test_gate_fails_closed_on_unknown_and_unexpected_skips() -> None:
    gate = _required_gate()
    assert "failure|cancelled)" in gate
    assert "unexpected or missing result" in gate
    assert "unexpected skip" in gate
    assert "failed=1" in gate
    assert "release-readiness" in gate
    assert "GITHUB_HEAD_REF" in gate
    assert "release-please--*" in gate
    assert "workflow_dispatch" in gate
    assert "GITHUB_EVENT_NAME" in gate
    assert "| $job | $result | $explanation |" in gate
    assert 'case "$result" in' in gate


def test_main_and_pr_concurrency_are_isolated() -> None:
    workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"))
    group = workflow["concurrency"]["group"]
    cancel = workflow["concurrency"]["cancel-in-progress"]
    assert "github.sha" in group
    assert "github.ref" in group
    assert "github.event_name == 'push'" in group
    assert "github.event_name != 'push'" in cancel

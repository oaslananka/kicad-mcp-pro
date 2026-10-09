"""Release Please must never publish without an explicit main-branch dispatch."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

WORKFLOW = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "release-please.yml"


def _workflow() -> dict:
    # PyYAML 1.1 treats the GitHub Actions `on` key as boolean True.
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    workflow["on"] = workflow.pop(True)
    return workflow


def test_release_please_is_daily_and_manually_triggered_only() -> None:
    events = _workflow()["on"]
    assert "push" not in events
    assert events["schedule"] == [{"cron": "37 3 * * *"}]
    operation = events["workflow_dispatch"]["inputs"]["operation"]
    assert operation["type"] == "choice"
    assert operation["options"] == ["prepare", "publish"]
    assert operation["default"] == "prepare"
    assert operation["required"] is True


def test_release_publishing_requires_explicit_dispatch_on_main() -> None:
    job = _workflow()["jobs"]["release"]
    assert "github.ref == 'refs/heads/main'" in job["if"]
    steps = job["steps"]
    action = next(
        step for step in steps if "googleapis/release-please-action@" in step.get("uses", "")
    )
    assert action["with"]["skip-github-release"] == (
        "${{ github.event_name != 'workflow_dispatch' || inputs.operation != 'publish' }}"
    )
    assert action["with"]["skip-github-pull-request"] == (
        "${{ github.event_name == 'workflow_dispatch' && inputs.operation == 'publish' }}"
    )
    assert next(step for step in steps if step.get("id") == "release-pr-branch")["if"] == (
        "${{ github.event_name == 'schedule' || inputs.operation == 'prepare' }}"
    )
    assert not any("github.event_name == 'push'" in str(step) for step in steps)


@pytest.mark.parametrize(
    ("event", "operation", "can_tag", "can_prepare"),
    [
        ("schedule", "", False, True),
        ("workflow_dispatch", "prepare", False, True),
        ("workflow_dispatch", "publish", True, False),
        ("push", "", False, False),
    ],
)
def test_release_mode_contract(
    event: str, operation: str, can_tag: bool, can_prepare: bool
) -> None:
    # Evaluate the simple boolean mode policy independently from the workflow YAML.
    tag = event == "workflow_dispatch" and operation == "publish"
    prepare = event == "schedule" or (event == "workflow_dispatch" and operation == "prepare")
    assert tag == can_tag
    assert prepare == can_prepare
    assert not (tag and prepare)

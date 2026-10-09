"""Release PR preparation is scheduled; publication needs a manual workflow."""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2] / ".github" / "workflows"


def _workflow(name: str) -> dict:
    # PyYAML 1.1 treats the Actions `on` keyword as boolean True.
    workflow = yaml.safe_load((ROOT / name).read_text(encoding="utf-8"))
    workflow["on"] = workflow.pop(True)
    return workflow


def test_daily_prepare_has_no_merge_or_publish_trigger() -> None:
    workflow = _workflow("release-please.yml")
    events = workflow["on"]
    assert set(events) == {"schedule", "workflow_dispatch"}
    assert events["schedule"] == [{"cron": "37 3 * * *"}]
    assert events["workflow_dispatch"] is None  # No user-controlled parameters.
    job = workflow["jobs"]["release"]
    assert "github.ref == 'refs/heads/main'" in job["if"]
    steps = job["steps"]
    action = next(
        step for step in steps if "googleapis/release-please-action@" in step.get("uses", "")
    )
    assert action["with"]["skip-github-release"] is True
    assert "skip-github-pull-request" not in action["with"]
    assert any(step.get("id") == "release-pr-branch" for step in steps)
    assert any("scripts/sync_release_artifacts.py --write" in str(step) for step in steps)


def test_only_manual_publish_creates_release_tags() -> None:
    workflow = _workflow("publish-release.yml")
    assert set(workflow["on"]) == {"workflow_dispatch"}
    assert workflow["on"]["workflow_dispatch"] is None  # Checkov CKV_GHA_7.
    job = workflow["jobs"]["publish"]
    assert "github.ref == 'refs/heads/main'" in job["if"]
    action = next(
        step for step in job["steps"] if "googleapis/release-please-action@" in step.get("uses", "")
    )
    assert action["with"]["skip-github-pull-request"] is True
    assert action["with"]["skip-github-release"] is False
    assert not any("sync_release_artifacts.py" in str(step) for step in job["steps"])


def test_publish_and_prepare_reuse_short_lived_github_app_with_pinned_actions() -> None:
    for filename, jobname in (
        ("release-please.yml", "release"),
        ("publish-release.yml", "publish"),
    ):
        steps = _workflow(filename)["jobs"][jobname]["steps"]
        token = next(step for step in steps if step.get("id") == "release-app-token")
        assert token["uses"].startswith("actions/create-github-app-token@")
        assert len(token["uses"].split("@", 1)[1]) == 40
        release = next(
            step for step in steps if "googleapis/release-please-action@" in step.get("uses", "")
        )
        assert len(release["uses"].split("@", 1)[1]) == 40
        assert "steps.release-app-token.outputs.token" in release["with"]["token"]
        assert release["with"]["config-file"] == "release-please-config.json"
        assert release["with"]["manifest-file"] == ".release-please-manifest.json"


def test_release_attestation_documentation_distinguishes_publisher_and_sbom() -> None:
    documentation = (ROOT.parents[1] / "docs" / "security" / "release-integrity.md").read_text(
        encoding="utf-8"
    )
    assert "--predicate-type https://cyclonedx.org/bom" in documentation
    assert "verify-pypi-provenance" in documentation
    assert "--publisher-environment pypi" in documentation
    assert "**not** SLSA build" in documentation
    assert "python -m sigstore verify identity \\" not in documentation

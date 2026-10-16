"""Release preparation stays separate; publishing requires verified CI + PR merge.

Production publication is never exercised by this test module.
"""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2] / ".github" / "workflows"


def _workflow(name: str) -> dict:
    # PyYAML 1.1 treats the Actions `on` keyword as boolean True.
    workflow = yaml.safe_load((ROOT / name).read_text(encoding="utf-8"))
    workflow["on"] = workflow.pop(True)
    return workflow


def test_daily_prepare_never_creates_releases() -> None:
    workflow = _workflow("release-please.yml")
    events = workflow["on"]
    assert set(events) == {"schedule", "workflow_dispatch"}
    assert events["schedule"] == [{"cron": "37 3 * * *"}]
    assert events["workflow_dispatch"] is None
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


def test_publish_is_called_only_by_trusted_ci_or_manual_recovery() -> None:
    workflow = _workflow("publish-release.yml")
    events = workflow["on"]
    assert set(events) == {"workflow_dispatch", "workflow_call"}
    assert events["workflow_dispatch"] is None
    assert events["workflow_call"] is None
    assert workflow["concurrency"]["cancel-in-progress"] is False
    assert workflow["concurrency"]["group"] == "publish-release-${{ github.repository }}"
    assert "workflow_run" not in events
    assert "push" not in events
    assert "schedule" not in events

    ci = _workflow("ci.yml")
    caller = ci["jobs"]["auto-publish-reviewed-release"]
    assert caller["needs"] == ["required-pr-gate", "sonarcloud"]
    # On main, release-readiness is intentionally skipped. Without an
    # explicit always(), GitHub's implicit success() prevents invocation
    # despite the direct Required PR Gate and SonarCloud jobs succeeding.
    assert caller["if"].lstrip().startswith("always() &&")
    assert "github.event_name == 'push'" in caller["if"]
    assert "github.ref == 'refs/heads/main'" in caller["if"]
    assert "needs.required-pr-gate.result == 'success'" in caller["if"]
    assert "needs.sonarcloud.result == 'success'" in caller["if"]
    assert caller["uses"] == "./.github/workflows/publish-release.yml"
    assert caller["secrets"] == "inherit"
    assert caller["permissions"] == {"contents": "read", "pull-requests": "read"}


def test_publish_requires_exact_reviewed_release_merge_before_minting_token() -> None:
    workflow = _workflow("publish-release.yml")
    authorize = workflow["jobs"]["authorize"]
    gate = authorize["steps"][0]
    condition = authorize["if"]
    shell = gate["run"]
    assert "github.event_name == 'push'" in condition
    assert "github.event_name == 'workflow_dispatch'" in condition
    assert "github.ref == 'refs/heads/main'" in condition
    assert gate["env"]["CI_HEAD_SHA"] == "${{ github.sha }}"
    assert '[[ "$CI_HEAD_SHA" =~ ^[0-9a-f]{40}$ ]]' in shell
    assert '"release-please--branches--main"' in shell
    assert ".merge_commit_sha == $sha" in shell
    assert ".head.repo.full_name == $repo" in shell
    assert '.base.ref == "main" and .base.repo.full_name == $repo' in shell
    assert 'merged_pr_json="$(gh api ' in shell
    assert "if ! jq -e" in shell  # ordinary main merges must be a no-op, not red CI.
    assert "approved=false" in shell
    assert "approved=true" in shell
    assert authorize["permissions"] == {"contents": "read", "pull-requests": "read"}
    assert not any("create-github-app-token" in str(step) for step in authorize["steps"])

    publish = workflow["jobs"]["publish"]
    assert publish["needs"] == "authorize"
    assert publish["if"] == "needs.authorize.outputs.approved == 'true'"
    assert authorize["outputs"]["approved"] == "${{ steps.gate.outputs.approved }}"
    assert any(
        "actions/create-github-app-token@" in step.get("uses", "") for step in publish["steps"]
    )
    assert not any("actions/checkout@" in str(step) for step in publish["steps"])


def test_publish_action_does_not_create_release_pr_or_sync_artifacts() -> None:
    job = _workflow("publish-release.yml")["jobs"]["publish"]
    action = next(
        step for step in job["steps"] if "googleapis/release-please-action@" in step.get("uses", "")
    )
    assert action["with"]["skip-github-pull-request"] is True
    assert action["with"]["skip-github-release"] is False
    assert not any("sync_release_artifacts.py" in str(step) for step in job["steps"])


def test_publish_and_prepare_use_short_lived_pinned_github_app_actions() -> None:
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
    assert "python -m sigstore verify identity " + chr(92) not in documentation

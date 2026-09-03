#!/usr/bin/env python3
"""Compare live GitHub Actions repository settings with the reviewed policy."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POLICY = ROOT / ".github" / "actions-policy.json"


def expected_selected_patterns(policy: dict[str, Any]) -> list[str]:
    """Return the selected-actions patterns implied by the reviewed allowlists."""
    direct = policy.get("allowed_action_repositories", [])
    transitive = policy.get("allowed_transitive_action_repositories", [])
    repositories = {
        str(repository)
        for repository in [*direct, *transitive]
        if isinstance(repository, str) and repository
    }
    return [f"{repository}@*" for repository in sorted(repositories)]


def validate_live_state(
    policy: dict[str, Any],
    actions_permissions: dict[str, Any],
    selected_actions: dict[str, Any],
    workflow_permissions: dict[str, Any],
) -> list[str]:
    """Return actionable errors for live settings that drift from policy."""
    settings = policy.get("repository_settings", {})
    if not isinstance(settings, dict):
        return ["actions-policy.json: repository_settings must be an object"]

    expected_actions = {
        "enabled": True,
        "allowed_actions": settings.get("allowed_actions"),
        "sha_pinning_required": settings.get("sha_pinning_required"),
    }
    expected_selected = {
        "github_owned_allowed": settings.get("github_owned_allowed"),
        "verified_allowed": settings.get("verified_allowed"),
        "patterns_allowed": expected_selected_patterns(policy),
    }
    expected_workflow = {
        "default_workflow_permissions": settings.get("default_workflow_permissions"),
        "can_approve_pull_request_reviews": settings.get("can_approve_pull_request_reviews"),
    }

    errors: list[str] = []
    for scope, actual, expected in (
        ("actions", actions_permissions, expected_actions),
        ("selected-actions", selected_actions, expected_selected),
        ("workflow", workflow_permissions, expected_workflow),
    ):
        for key, expected_value in expected.items():
            actual_value = actual.get(key)
            if key == "patterns_allowed":
                actual_value = sorted(str(item) for item in (actual_value or []))
                expected_value = sorted(str(item) for item in (expected_value or []))
            if actual_value != expected_value:
                errors.append(
                    f"{scope}.{key} drift: actual={actual_value!r} expected={expected_value!r}"
                )
    return errors



def validate_environment_protection(
    policy: dict[str, Any], environments: dict[str, dict[str, Any]]
) -> list[str]:
    expected = policy.get("protected_publish_environments", {})
    if not isinstance(expected, dict):
        return ["actions-policy.json: protected_publish_environments must be an object"]
    errors: list[str] = []
    for name, requirement in expected.items():
        if not isinstance(name, str) or not isinstance(requirement, dict):
            errors.append("actions-policy.json: invalid protected publish environment entry")
            continue
        live = environments.get(name, {})
        rules = live.get("protection_rules", []) if isinstance(live, dict) else []
        reviewer_rule = next(
            (
                rule
                for rule in rules
                if isinstance(rule, dict) and rule.get("type") == "required_reviewers"
            ),
            {},
        )
        reviewers = reviewer_rule.get("reviewers", []) if isinstance(reviewer_rule, dict) else []
        actual_reviewers = sorted(
            str(item.get("reviewer", {}).get("login"))
            for item in reviewers
            if isinstance(item, dict) and isinstance(item.get("reviewer"), dict)
        )
        required_reviewers = sorted(
            str(item) for item in requirement.get("required_reviewers", [])
        )
        if actual_reviewers != required_reviewers:
            errors.append(
                f"{name}.required_reviewers drift: actual={actual_reviewers!r} "
                f"expected={required_reviewers!r}"
            )
        actual_prevent = reviewer_rule.get("prevent_self_review") if reviewer_rule else None
        expected_prevent = requirement.get("prevent_self_review")
        if actual_prevent != expected_prevent:
            errors.append(
                f"{name}.prevent_self_review drift: actual={actual_prevent!r} "
                f"expected={expected_prevent!r}"
            )
    return errors

def _load_policy(path: Path) -> dict[str, Any]:
    resolved = path.expanduser().resolve(strict=True)
    resolved.relative_to(ROOT.resolve())
    payload = json.loads(resolved.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("GitHub Actions policy root must be an object")
    return payload


def _repository_from_origin() -> str:
    git = shutil.which("git")
    if git is None:
        raise RuntimeError("git executable is unavailable")
    completed = subprocess.run(
        [git, "remote", "get-url", "origin"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise RuntimeError("could not resolve GitHub repository from origin")
    remote = completed.stdout.strip()
    match = re.search(r"github\.com[/:](?P<repo>[^/]+/[^/]+?)(?:\.git)?$", remote)
    if match is None:
        raise RuntimeError(f"origin is not a GitHub repository: {remote!r}")
    return match.group("repo")


def _gh_api(repository: str, suffix: str) -> dict[str, Any]:
    endpoint = f"repos/{repository}/{suffix}"
    gh = shutil.which("gh")
    if gh is None:
        raise RuntimeError("gh executable is unavailable")
    completed = subprocess.run(
        [gh, "api", endpoint],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise RuntimeError(f"gh api {endpoint} failed: {detail}")
    payload = json.loads(completed.stdout)
    if not isinstance(payload, dict):
        raise RuntimeError(f"gh api {endpoint} returned a non-object payload")
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    parser.add_argument("--repository", default=os.environ.get("GITHUB_REPOSITORY", ""))
    args = parser.parse_args(argv)

    try:
        policy = _load_policy(args.policy)
        repository = args.repository.strip() or _repository_from_origin()
        actions = _gh_api(repository, "actions/permissions")
        selected = _gh_api(repository, "actions/permissions/selected-actions")
        workflow = _gh_api(repository, "actions/permissions/workflow")
        errors = validate_live_state(policy, actions, selected, workflow)
        expected_environments = policy.get("protected_publish_environments", {})
        if not isinstance(expected_environments, dict):
            raise ValueError("protected_publish_environments must be an object")
        live_environments = {
            name: _gh_api(repository, f"environments/{name}")
            for name in expected_environments
        }
        errors.extend(validate_environment_protection(policy, live_environments))
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"GitHub repository settings check failed: {exc}", file=sys.stderr)
        return 2

    if errors:
        print(f"GitHub repository settings drift detected for {repository}:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1

    print(f"GitHub repository settings match policy for {repository}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

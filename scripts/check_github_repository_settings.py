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
from http.client import HTTPException, HTTPSConnection
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POLICY = ROOT / ".github" / "actions-policy.json"
_REPOSITORY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,99}/[A-Za-z0-9][A-Za-z0-9_.-]{0,99}$")
_PATH_SEGMENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


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


def _required_reviewer_rule(live: dict[str, Any]) -> dict[str, Any]:
    rules = live.get("protection_rules", [])
    if not isinstance(rules, list):
        return {}
    return next(
        (
            rule
            for rule in rules
            if isinstance(rule, dict) and rule.get("type") == "required_reviewers"
        ),
        {},
    )


def _reviewer_logins(rule: dict[str, Any]) -> list[str]:
    reviewers = rule.get("reviewers", [])
    if not isinstance(reviewers, list):
        return []
    return sorted(
        str(item["reviewer"]["login"])
        for item in reviewers
        if isinstance(item, dict)
        and isinstance(item.get("reviewer"), dict)
        and isinstance(item["reviewer"].get("login"), str)
    )


def _environment_requirement_errors(
    name: str, requirement: dict[str, Any], live: dict[str, Any]
) -> list[str]:
    reviewer_rule = _required_reviewer_rule(live)
    actual_reviewers = _reviewer_logins(reviewer_rule)
    required_reviewers = sorted(str(item) for item in requirement.get("required_reviewers", []))
    errors: list[str] = []
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
        errors.extend(_environment_requirement_errors(name, requirement, live))
    return errors


def _load_policy(path: Path) -> dict[str, Any]:
    resolved = path.expanduser().resolve(strict=True)
    resolved.relative_to(ROOT.resolve())
    payload = json.loads(resolved.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("GitHub Actions policy root must be an object")
    return payload


def validate_repository_name(repository: str) -> str:
    """Validate the canonical GitHub owner/repository identifier."""
    if _REPOSITORY_RE.fullmatch(repository) is None:
        raise ValueError("repository must be a safe owner/repository identifier")
    return repository


def _validated_path_segment(segment: str) -> str:
    if _PATH_SEGMENT_RE.fullmatch(segment) is None:
        raise ValueError(f"unsafe GitHub API path segment: {segment!r}")
    return segment


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


def _github_token() -> str:
    token = os.environ.get("GH_TOKEN", "").strip()
    if token:
        return token
    gh = shutil.which("gh")
    if gh is None:
        raise RuntimeError("gh executable is unavailable and GH_TOKEN is unset")
    completed = subprocess.run(
        [gh, "auth", "token"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    token = completed.stdout.strip()
    if completed.returncode != 0 or not token:
        detail = completed.stderr.strip() or "gh auth token returned no credential"
        raise RuntimeError(f"could not resolve GitHub API credential: {detail}")
    return token


def _github_api(repository: str, path_segments: tuple[str, ...], token: str) -> dict[str, Any]:
    owner, name = validate_repository_name(repository).split("/", maxsplit=1)
    segments = [owner, name, *(_validated_path_segment(item) for item in path_segments)]
    path = "/repos/" + "/".join(segments)
    connection = HTTPSConnection("api.github.com", timeout=30)
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "User-Agent": "kicad-mcp-repository-settings-audit",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    try:
        connection.request("GET", path, headers=headers)
        response = connection.getresponse()
        body = response.read()
    finally:
        connection.close()
    if not 200 <= response.status < 300:
        detail = body.decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"GitHub API {path} failed with HTTP {response.status}: {detail}")
    payload = json.loads(body.decode("utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"GitHub API {path} returned a non-object payload")
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    parser.add_argument("--repository", default=os.environ.get("GITHUB_REPOSITORY", ""))
    args = parser.parse_args(argv)

    try:
        policy = _load_policy(args.policy)
        repository = validate_repository_name(args.repository.strip() or _repository_from_origin())
        token = _github_token()
        actions = _github_api(repository, ("actions", "permissions"), token)
        selected = _github_api(repository, ("actions", "permissions", "selected-actions"), token)
        workflow = _github_api(repository, ("actions", "permissions", "workflow"), token)
        errors = validate_live_state(policy, actions, selected, workflow)
        expected_environments = policy.get("protected_publish_environments", {})
        if not isinstance(expected_environments, dict):
            raise ValueError("protected_publish_environments must be an object")
        live_environments = {
            name: _github_api(repository, ("environments", _validated_path_segment(name)), token)
            for name in expected_environments
        }
        errors.extend(validate_environment_protection(policy, live_environments))
    except (OSError, ValueError, RuntimeError, HTTPException) as exc:
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

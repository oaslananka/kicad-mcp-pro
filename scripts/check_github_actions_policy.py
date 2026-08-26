"""Validate the repository's least-privilege GitHub Actions policy."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import cast

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POLICY = REPO_ROOT / ".github" / "actions-policy.json"
SHA_REF = re.compile(r"^[0-9a-fA-F]{40}$")


def _load_yaml(path: Path) -> dict[str, object]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path}: workflow root must be a mapping")
    return data


def load_policy(
    path: Path = DEFAULT_POLICY, *, allowed_root: Path = REPO_ROOT
) -> dict[str, object]:
    try:
        resolved_root = allowed_root.expanduser().resolve(strict=True)
        candidate = path.expanduser()
        resolved = (
            (resolved_root / candidate).resolve(strict=True)
            if not candidate.is_absolute()
            else candidate.resolve(strict=True)
        )
        resolved.relative_to(resolved_root)
    except (OSError, ValueError) as exc:
        raise ValueError(
            "GitHub Actions policy must be an existing file inside the checker repository root"
        ) from exc
    if not resolved.is_file():
        raise ValueError(
            "GitHub Actions policy must be an existing file inside the checker repository root"
        )

    data = json.loads(resolved.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{resolved}: policy root must be an object")
    return data


def _iter_uses(value: object) -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            if key == "uses" and isinstance(child, str):
                found.append(child)
            found.extend(_iter_uses(child))
    elif isinstance(value, list):
        for child in value:
            found.extend(_iter_uses(child))
    return found


def has_sha_pinned_action(workflow_text: str, action_path: str) -> bool:
    """Return whether workflow text uses an Action path at an immutable SHA."""
    pattern = re.compile(
        rf"(?m)^\s*(?:-\s*)?uses:\s*['\"]?{re.escape(action_path)}@"
        rf"[0-9a-fA-F]{{40}}['\"]?(?:\s+#.*)?\s*$"
    )
    return pattern.search(workflow_text) is not None


def _permission_writes(value: object, context: str, errors: list[str]) -> set[str]:
    if value is None:
        return set()
    if not isinstance(value, dict):
        errors.append(f"{context}: permissions must be an explicit mapping, not {value!r}")
        return set()
    writes: set[str] = set()
    for scope, access in value.items():
        normalized = str(access).lower()
        if normalized not in {"read", "write", "none"}:
            errors.append(f"{context}: unsupported permission {scope}={access!r}")
        if normalized == "write":
            writes.add(str(scope))
    return writes


def validate_repository(root: Path, policy: dict[str, object]) -> list[str]:
    errors: list[str] = []
    settings = policy.get("repository_settings")
    expected_settings = {
        "allowed_actions": "selected",
        "can_approve_pull_request_reviews": False,
        "default_workflow_permissions": "read",
        "github_owned_allowed": True,
        "sha_pinning_required": True,
        "verified_allowed": False,
    }
    if settings != expected_settings:
        errors.append("actions-policy.json: repository_settings do not match the hardened baseline")

    github_owned = set(cast(list[str], policy.get("github_owned_action_owners", [])))
    allowed_repositories = set(cast(list[str], policy.get("allowed_action_repositories", [])))
    allowed_transitive_repositories = set(
        cast(list[str], policy.get("allowed_transitive_action_repositories", []))
    )
    overlapping_repositories = sorted(allowed_repositories & allowed_transitive_repositories)
    if overlapping_repositories:
        errors.append(
            "actions-policy.json: repositories cannot be both direct and transitive: "
            f"{overlapping_repositories!r}"
        )
    permitted_repositories = allowed_repositories | allowed_transitive_repositories
    expected_writes = policy.get("workflow_write_permissions", {})
    if not isinstance(expected_writes, dict):
        errors.append("actions-policy.json: workflow_write_permissions must be an object")
        expected_writes = {}

    workflows = sorted((root / ".github" / "workflows").glob("*.y*ml"))
    actual_third_party: set[str] = set()
    actual_writes: dict[str, dict[str, list[str]]] = {}

    for workflow in workflows:
        try:
            data = _load_yaml(workflow)
        except (OSError, ValueError, yaml.YAMLError) as exc:
            errors.append(str(exc))
            continue

        top_permissions = data.get("permissions")
        top_writes = _permission_writes(
            top_permissions, f"{workflow.name}: workflow permissions", errors
        )
        if top_writes:
            errors.append(
                f"{workflow.name}: write permissions must be scoped to a job: {sorted(top_writes)}"
            )
        if not isinstance(top_permissions, dict) or top_permissions.get("contents") != "read":
            errors.append(f"{workflow.name}: workflow permissions must declare contents: read")

        jobs = data.get("jobs", {})
        workflow_writes: dict[str, list[str]] = {}
        if not isinstance(jobs, dict):
            errors.append(f"{workflow.name}: jobs must be a mapping")
            jobs = {}
        for job_name, job in jobs.items():
            if not isinstance(job, dict):
                continue
            writes = _permission_writes(
                job.get("permissions"), f"{workflow.name}:{job_name} permissions", errors
            )
            if writes:
                workflow_writes[str(job_name)] = sorted(writes)
        if workflow_writes:
            actual_writes[workflow.name] = workflow_writes

        for action in _iter_uses(data):
            if action.startswith("./") or action.startswith("docker://"):
                continue
            if "@" not in action:
                errors.append(f"{workflow.name}: action has no immutable ref: {action}")
                continue
            action_path, ref = action.rsplit("@", 1)
            if not SHA_REF.fullmatch(ref):
                errors.append(
                    f"{workflow.name}: action is not pinned to a 40-character SHA: {action}"
                )
            parts = action_path.split("/")
            if len(parts) < 2:
                errors.append(f"{workflow.name}: malformed action reference: {action}")
                continue
            repository = "/".join(parts[:2])
            if parts[0] not in github_owned:
                actual_third_party.add(repository)
                if repository in allowed_transitive_repositories:
                    errors.append(
                        f"{workflow.name}: directly used Action must be promoted from the "
                        f"transitive allowlist: {repository}"
                    )
                elif repository not in permitted_repositories:
                    errors.append(
                        f"{workflow.name}: action repository is not allowlisted: {repository}"
                    )

    normalized_expected: dict[str, dict[str, list[str]]] = {}
    for workflow, jobs in expected_writes.items():
        if not isinstance(jobs, dict):
            errors.append(f"actions-policy.json: {workflow} write policy must be an object")
            continue
        normalized_expected[str(workflow)] = {
            str(job): sorted(str(scope) for scope in scopes)
            for job, scopes in jobs.items()
            if isinstance(scopes, list)
        }
    if actual_writes != normalized_expected:
        errors.append(
            "workflow write-permission matrix differs from actions-policy.json: "
            f"actual={actual_writes!r} expected={normalized_expected!r}"
        )

    if actual_third_party != allowed_repositories:
        errors.append(
            "third-party Actions allowlist is stale: "
            f"used={sorted(actual_third_party)!r} allowed={sorted(allowed_repositories)!r}"
        )

    codeowners_path = root / ".github" / "CODEOWNERS"
    codeowners = {
        line.strip()
        for line in codeowners_path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    required_rules = set(cast(list[str], policy.get("required_codeowner_rules", [])))
    missing_rules = sorted(required_rules - codeowners)
    if missing_rules:
        errors.append(f"CODEOWNERS is missing protected rules: {missing_rules!r}")

    return errors


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=REPO_ROOT)
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    args = parser.parse_args()

    root = args.root.expanduser().resolve(strict=True)
    policy = load_policy(args.policy)
    errors = validate_repository(root, policy)
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        raise SystemExit(1)

    workflow_count = len(list((root / ".github" / "workflows").glob("*.y*ml")))
    print(f"GitHub Actions policy passed for {workflow_count} workflows.")


if __name__ == "__main__":
    main()

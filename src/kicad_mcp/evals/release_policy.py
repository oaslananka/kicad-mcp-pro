"""Risk-based live-model assurance and approved-baseline reuse policy."""

from __future__ import annotations

import fnmatch
import hashlib
import os
import re
import subprocess
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from shutil import which
from typing import Any, Literal, cast

import yaml

from ..path_safety import resolve_repo_or_temp

_REPO_ROOT = Path(__file__).resolve().parents[3]

AssuranceMode = Literal["none", "smoke", "full"]

_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_POLICY_KEYS = frozenset(
    {
        "schema_version",
        "baseline_max_age_days",
        "release_pull_request_head",
        "minimum_smoke_configurations",
        "agent_contract_paths",
    }
)
_BASELINE_KEYS = frozenset(
    {
        "schema_version",
        "approved",
        "approved_at",
        "source_revision",
        "agent_contract_digest",
        "evidence",
        "minimum_repeats",
        "required_configurations",
        "configurations",
    }
)


class ReleasePolicyError(ValueError):
    """Raised when release-assurance policy or baseline metadata is invalid."""


@dataclass(frozen=True, slots=True)
class ReleasePolicyConfig:
    """Versioned risk-classification policy consumed by release automation."""

    baseline_max_age_days: int
    release_pull_request_head: str
    minimum_smoke_configurations: int
    agent_contract_paths: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class BaselineMetadata:
    """Audit metadata required to reuse an approved live-model baseline."""

    approved: bool
    approved_at: date | None
    source_revision: str | None
    agent_contract_digest: str | None
    workflow_run_id: int | None
    aggregate_sha256: str | None
    required_configurations: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ReleasePolicyDecision:
    """One deterministic assurance decision for a release candidate."""

    mode: AssuranceMode
    reason: str
    baseline_age_days: int | None
    current_contract_digest: str
    baseline_contract_digest: str | None
    required_configurations: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "mode": self.mode,
            "reason": self.reason,
            "baseline_age_days": self.baseline_age_days,
            "current_contract_digest": self.current_contract_digest,
            "baseline_contract_digest": self.baseline_contract_digest,
            "required_configurations": list(self.required_configurations),
        }


def _mapping(value: object, description: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ReleasePolicyError(f"{description} must be a mapping.")
    return cast(dict[str, Any], value)


def _string_list(value: object, description: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise ReleasePolicyError(f"{description} must be a non-empty list of strings.")
    items: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ReleasePolicyError(f"{description} must contain non-empty strings.")
        items.append(item.strip())
    if len(items) != len(set(items)):
        raise ReleasePolicyError(f"{description} must not contain duplicates.")
    return tuple(items)


def load_release_policy(path: str | Path) -> ReleasePolicyConfig:
    """Load one strict versioned release-assurance policy."""
    raw = _mapping(
        yaml.safe_load(
            resolve_repo_or_temp(path, repo_root=_REPO_ROOT).read_text(encoding="utf-8")
        ),
        "Release policy",
    )
    unknown = sorted(set(raw) - _POLICY_KEYS)
    if unknown:
        raise ReleasePolicyError(f"Release policy has unsupported fields: {unknown}.")
    if raw.get("schema_version") != 1:
        raise ReleasePolicyError("Release policy schema_version must be 1.")

    max_age = raw.get("baseline_max_age_days")
    if isinstance(max_age, bool) or not isinstance(max_age, int) or max_age < 1:
        raise ReleasePolicyError("baseline_max_age_days must be an integer >= 1.")
    release_head = raw.get("release_pull_request_head")
    if not isinstance(release_head, str) or not release_head.strip():
        raise ReleasePolicyError("release_pull_request_head must be a non-empty string.")
    minimum_smoke = raw.get("minimum_smoke_configurations")
    if isinstance(minimum_smoke, bool) or not isinstance(minimum_smoke, int) or minimum_smoke < 1:
        raise ReleasePolicyError("minimum_smoke_configurations must be an integer >= 1.")
    paths = _string_list(raw.get("agent_contract_paths"), "agent_contract_paths")
    for pattern in paths:
        if pattern.startswith("/") or ".." in Path(pattern).parts:
            raise ReleasePolicyError(f"Unsafe agent contract path pattern: {pattern!r}.")

    return ReleasePolicyConfig(
        baseline_max_age_days=max_age,
        release_pull_request_head=release_head.strip(),
        minimum_smoke_configurations=minimum_smoke,
        agent_contract_paths=paths,
    )


def load_baseline_metadata(path: str | Path) -> BaselineMetadata:
    raw = _mapping(
        yaml.safe_load(
            resolve_repo_or_temp(path, repo_root=_REPO_ROOT).read_text(encoding="utf-8")
        ),
        "Baseline",
    )
    unknown = sorted(set(raw) - _BASELINE_KEYS)
    if unknown:
        raise ReleasePolicyError(f"Baseline has unsupported fields: {unknown}.")
    if raw.get("schema_version") != 1:
        raise ReleasePolicyError("Baseline schema_version must be 1.")
    approved = raw.get("approved")
    if not isinstance(approved, bool):
        raise ReleasePolicyError("Baseline approved must be boolean.")
    required = _string_list(raw.get("required_configurations"), "required_configurations")
    if len(required) < 3:
        raise ReleasePolicyError("Baseline needs at least three required configurations.")
    _mapping(raw.get("configurations", {}), "Baseline configurations")

    approved_at: date | None = None
    source_revision: str | None = None
    contract_digest: str | None = None
    workflow_run_id: int | None = None
    aggregate_sha256: str | None = None

    if approved:
        approved_at_raw = raw.get("approved_at")
        if not isinstance(approved_at_raw, str):
            raise ReleasePolicyError("Approved baseline approved_at must be an ISO date.")
        try:
            approved_at = date.fromisoformat(approved_at_raw)
        except ValueError as exc:
            raise ReleasePolicyError("Approved baseline approved_at must be an ISO date.") from exc

        source_revision_raw = raw.get("source_revision")
        if not isinstance(source_revision_raw, str) or not _SHA40.fullmatch(source_revision_raw):
            raise ReleasePolicyError(
                "Approved baseline source_revision must be a lowercase Git SHA."
            )
        source_revision = source_revision_raw

        digest_raw = raw.get("agent_contract_digest")
        if not isinstance(digest_raw, str) or not _SHA256.fullmatch(digest_raw):
            raise ReleasePolicyError(
                "Approved baseline agent_contract_digest must be a lowercase SHA-256."
            )
        contract_digest = digest_raw

        evidence = _mapping(raw.get("evidence"), "Approved baseline evidence")
        run_id = evidence.get("workflow_run_id")
        if isinstance(run_id, bool) or not isinstance(run_id, int) or run_id < 1:
            raise ReleasePolicyError("Approved baseline evidence workflow_run_id must be positive.")
        workflow_run_id = run_id
        aggregate_raw = evidence.get("aggregate_sha256")
        if not isinstance(aggregate_raw, str) or not _SHA256.fullmatch(aggregate_raw):
            raise ReleasePolicyError(
                "Approved baseline evidence aggregate_sha256 must be a lowercase SHA-256."
            )
        aggregate_sha256 = aggregate_raw

    return BaselineMetadata(
        approved=approved,
        approved_at=approved_at,
        source_revision=source_revision,
        agent_contract_digest=contract_digest,
        workflow_run_id=workflow_run_id,
        aggregate_sha256=aggregate_sha256,
        required_configurations=required,
    )


def _git(repo_root: Path, *arguments: str, text: bool = True) -> str | bytes:
    git = which("git")
    if git is None:
        raise ReleasePolicyError("git executable is unavailable.")
    environment = os.environ.copy()
    for variable in (
        "GIT_ALTERNATE_OBJECT_DIRECTORIES",
        "GIT_COMMON_DIR",
        "GIT_DIR",
        "GIT_INDEX_FILE",
        "GIT_OBJECT_DIRECTORY",
        "GIT_WORK_TREE",
    ):
        environment.pop(variable, None)
    result = subprocess.run(
        [git, *arguments],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=text,
        env=environment,
    )
    if result.returncode != 0:
        stderr = result.stderr.strip() if text else result.stderr.decode("utf-8", "replace").strip()
        raise ReleasePolicyError(f"Git command failed: {' '.join(arguments)}: {stderr}")
    return cast(str | bytes, result.stdout)


def _matches_contract(path: str, policy: ReleasePolicyConfig) -> bool:
    return any(fnmatch.fnmatchcase(path, pattern) for pattern in policy.agent_contract_paths)


def compute_agent_contract_digest(
    repo_root: str | Path,
    policy: ReleasePolicyConfig,
    *,
    ref: str = "HEAD",
) -> str:
    """Hash configured tracked file paths at one exact Git revision."""
    root = Path(repo_root)
    listed = cast(str, _git(root, "ls-tree", "-r", "--name-only", ref))
    paths = sorted(path for path in listed.splitlines() if _matches_contract(path, policy))
    if not paths:
        raise ReleasePolicyError("Agent contract path set matched no tracked files.")

    digest = hashlib.sha256()
    for path in paths:
        content = cast(bytes, _git(root, "show", f"{ref}:{path}", text=False))
        encoded_path = path.encode("utf-8")
        digest.update(encoded_path)
        digest.update(b"\0")
        digest.update(str(len(content)).encode("ascii"))
        digest.update(b"\0")
        digest.update(content)
        digest.update(b"\0")
    return digest.hexdigest()


def contract_changed_between(
    repo_root: str | Path,
    policy: ReleasePolicyConfig,
    *,
    base_ref: str,
    head_ref: str,
) -> bool:
    """Return true when configured model-facing content differs between revisions."""
    if not base_ref or set(base_ref) == {"0"}:
        return True
    try:
        base_digest = compute_agent_contract_digest(repo_root, policy, ref=base_ref)
        head_digest = compute_agent_contract_digest(repo_root, policy, ref=head_ref)
    except ReleasePolicyError:
        return True
    return base_digest != head_digest


def evaluate_push_assurance(
    *,
    repo_root: str | Path,
    policy_path: str | Path,
    baseline_path: str | Path,
    base_ref: str,
    head_ref: str,
) -> ReleasePolicyDecision:
    """Run smoke on main only when the configured agent contract changed."""
    policy = load_release_policy(policy_path)
    baseline = load_baseline_metadata(baseline_path)
    current_digest = compute_agent_contract_digest(repo_root, policy, ref=head_ref)
    changed = contract_changed_between(
        repo_root,
        policy,
        base_ref=base_ref,
        head_ref=head_ref,
    )
    return ReleasePolicyDecision(
        mode="smoke" if changed else "none",
        reason="agent_contract_changed_on_main" if changed else "no_agent_contract_change",
        baseline_age_days=None,
        current_contract_digest=current_digest,
        baseline_contract_digest=baseline.agent_contract_digest,
        required_configurations=baseline.required_configurations,
    )


def evaluate_noop_assurance(
    *,
    repo_root: str | Path,
    policy_path: str | Path,
    baseline_path: str | Path,
    ref: str = "HEAD",
) -> ReleasePolicyDecision:
    """Return a stable successful decision for non-release pull requests."""
    policy = load_release_policy(policy_path)
    baseline = load_baseline_metadata(baseline_path)
    return ReleasePolicyDecision(
        mode="none",
        reason="not_release_pull_request",
        baseline_age_days=None,
        current_contract_digest=compute_agent_contract_digest(repo_root, policy, ref=ref),
        baseline_contract_digest=baseline.agent_contract_digest,
        required_configurations=baseline.required_configurations,
    )


def evaluate_release_readiness(
    *,
    repo_root: str | Path,
    policy_path: str | Path,
    baseline_path: str | Path,
    ref: str = "HEAD",
    today: date | None = None,
) -> ReleasePolicyDecision:
    """Require a full gate only when an approved reusable baseline is unavailable."""
    policy = load_release_policy(policy_path)
    baseline = load_baseline_metadata(baseline_path)
    current_digest = compute_agent_contract_digest(repo_root, policy, ref=ref)

    if not baseline.approved:
        return ReleasePolicyDecision(
            mode="full",
            reason="baseline_unapproved",
            baseline_age_days=None,
            current_contract_digest=current_digest,
            baseline_contract_digest=None,
            required_configurations=baseline.required_configurations,
        )

    approved_at = baseline.approved_at
    baseline_digest = baseline.agent_contract_digest
    if approved_at is None or baseline_digest is None:
        raise ReleasePolicyError("Approved baseline metadata is incomplete.")
    reference_date = date.today() if today is None else today
    age_days = (reference_date - approved_at).days
    if age_days < 0:
        return ReleasePolicyDecision(
            mode="full",
            reason="baseline_approval_in_future",
            baseline_age_days=age_days,
            current_contract_digest=current_digest,
            baseline_contract_digest=baseline_digest,
            required_configurations=baseline.required_configurations,
        )
    if age_days > policy.baseline_max_age_days:
        return ReleasePolicyDecision(
            mode="full",
            reason="baseline_stale",
            baseline_age_days=age_days,
            current_contract_digest=current_digest,
            baseline_contract_digest=baseline_digest,
            required_configurations=baseline.required_configurations,
        )
    if current_digest != baseline.agent_contract_digest:
        return ReleasePolicyDecision(
            mode="full",
            reason="agent_contract_changed",
            baseline_age_days=age_days,
            current_contract_digest=current_digest,
            baseline_contract_digest=baseline_digest,
            required_configurations=baseline.required_configurations,
        )
    return ReleasePolicyDecision(
        mode="smoke",
        reason="approved_baseline_reusable",
        baseline_age_days=age_days,
        current_contract_digest=current_digest,
        baseline_contract_digest=baseline_digest,
        required_configurations=baseline.required_configurations,
    )


__all__ = [
    "BaselineMetadata",
    "ReleasePolicyConfig",
    "ReleasePolicyDecision",
    "ReleasePolicyError",
    "compute_agent_contract_digest",
    "contract_changed_between",
    "evaluate_noop_assurance",
    "evaluate_push_assurance",
    "evaluate_release_readiness",
    "load_baseline_metadata",
    "load_release_policy",
]

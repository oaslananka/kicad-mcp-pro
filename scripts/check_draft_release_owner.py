"""Read-only #1179 draft Release and trusted owner-run identity preflight.

This is NOT a concurrency lock or permission to upload/publish. It verifies
GitHub API identities for a future single-writer draft-first orchestrator.
"""

from __future__ import annotations

import argparse
import json
from typing import Any, Protocol

from scripts.check_draft_release_inventory import _draft_release
from scripts.check_release_family_inventory import _TAG
from scripts.stage_draft_release_assets import _SHA, GitHubCLI, _valid_inputs

_OWNER_PATH = ".github/workflows/publish-release.yml"
# Only the reviewed personal repository owner may initiate or re-run
# a release-authorizing workflow_dispatch; repository write access is broader.
_TRUSTED_DISPATCH_OWNER = {"oaslananka/kicad-mcp-pro": "oaslananka"}
_OWNER_ID = 285490571
_REPOSITORY_ID = 1255527274
_TAG_RULESET_ID = 24511858
_TAG_PATTERNS = (
    "refs/tags/mcp-server-v*",
    "refs/tags/mcp-npm-v*",
    "refs/tags/protocol-schemas-v*",
    "refs/tags/kicad-mcp-gui-v*",
)


class OwnerRunClient(Protocol):
    def workflow_run(self, repo: str, run_id: int) -> dict[str, Any]: ...


class OwnerClient(OwnerRunClient, Protocol):
    def release(self, repo: str, release_id: int) -> dict[str, Any]: ...

    def tag_commit(self, repo: str, tag: str) -> str: ...

    def tag_ruleset(self, repo: str) -> dict[str, Any]: ...


class OwnerGitHubCLI(GitHubCLI):
    def tag_ruleset(self, repo: str) -> dict[str, Any]:
        return self._json(f"repos/{repo}/rulesets/{_TAG_RULESET_ID}")

    def workflow_run(self, repo: str, run_id: int) -> dict[str, Any]:
        return self._json(f"repos/{repo}/actions/runs/{run_id}")


def _exact_id(value: object, expected: int) -> bool:
    return type(value) is int and value == expected


def verify_tag_protection(client: OwnerClient, repo: str, tag: str) -> None:
    """Check the exact reviewed tag ruleset, not just a tag name or ref SHA."""
    if repo not in _TRUSTED_DISPATCH_OWNER or _TAG.fullmatch(tag) is None:
        raise ValueError("unsupported release tag or repository")
    policy = client.tag_ruleset(repo)
    if (
        not isinstance(policy, dict)
        or not _exact_id(policy.get("id"), _TAG_RULESET_ID)
        or policy.get("name") != "release-tags"
        or policy.get("source") != repo
        or policy.get("source_type") != "Repository"
        or policy.get("target") != "tag"
        or policy.get("enforcement") != "active"
        or policy.get("bypass_actors") != []
    ):
        raise ValueError("tag protection identity, enforcement or bypass visibility mismatch")
    conditions = policy.get("conditions")
    if not isinstance(conditions, dict) or set(conditions) != {"ref_name"}:
        raise ValueError("tag protection conditions mismatch")
    refs = conditions["ref_name"]
    if not isinstance(refs, dict) or set(refs) != {"include", "exclude"}:
        raise ValueError("tag protection ref conditions mismatch")
    includes = refs["include"]
    if (
        refs["exclude"] != []
        or not isinstance(includes, list)
        or len(includes) != len(_TAG_PATTERNS)
        or any(pattern not in includes for pattern in _TAG_PATTERNS)
    ):
        raise ValueError("tag protection ref coverage mismatch")
    rules = policy.get("rules")
    if not isinstance(rules, list) or any(
        rule not in rules for rule in ({"type": "deletion"}, {"type": "update"})
    ):
        raise ValueError("tag protection update or deletion rule missing")


def verify_active_owner_run(
    client: OwnerRunClient,
    *,
    repo: str,
    owner_run_id: int,
    owner_run_attempt: int,
    owner_head_sha: str,
) -> None:
    """Check active production owner identity without draft or ruleset access."""
    expected_actor = _TRUSTED_DISPATCH_OWNER.get(repo)
    if expected_actor is None:
        raise ValueError("no trusted owner dispatch principal for repository")
    if (
        type(owner_run_id) is not int
        or owner_run_id <= 0
        or type(owner_run_attempt) is not int
        or owner_run_attempt <= 0
        or not _SHA.fullmatch(owner_head_sha)
    ):
        raise ValueError("invalid owner workflow run identity")
    run = client.workflow_run(repo, owner_run_id)
    if not isinstance(run, dict):
        raise ValueError("GitHub owner workflow response is invalid")
    expected_run_url = f"https://api.github.com/repos/{repo}/actions/runs/{owner_run_id}"
    run_repo = run.get("repository")
    head_repo = run.get("head_repository")
    if (
        run.get("id") != owner_run_id
        or type(run.get("id")) is not int
        or run.get("url") != expected_run_url
        or not isinstance(run_repo, dict)
        or run_repo.get("full_name") != repo
        or not _exact_id(run_repo.get("id"), _REPOSITORY_ID)
        or not isinstance(head_repo, dict)
        or head_repo.get("full_name") != repo
        or not _exact_id(head_repo.get("id"), _REPOSITORY_ID)
    ):
        raise ValueError("workflow run belongs to an unexpected repository")
    actor = run.get("actor")
    triggering_actor = run.get("triggering_actor")
    if (
        not isinstance(actor, dict)
        or actor.get("login") != expected_actor
        or not _exact_id(actor.get("id"), _OWNER_ID)
        or not isinstance(triggering_actor, dict)
        or triggering_actor.get("login") != expected_actor
        or not _exact_id(triggering_actor.get("id"), _OWNER_ID)
    ):
        raise ValueError("workflow run actor is not the trusted owner")

    if (
        run.get("path") != _OWNER_PATH
        or run.get("event") != "workflow_dispatch"
        or run.get("head_branch") != "main"
        or run.get("head_sha") != owner_head_sha
        or type(run.get("run_attempt")) is not int
        or run["run_attempt"] != owner_run_attempt
        or run.get("status") != "in_progress"
        or run.get("conclusion") is not None
    ):
        raise ValueError("workflow run is not the expected active main owner dispatch")


def verify_owner(
    client: OwnerClient,
    *,
    repo: str,
    release_id: int,
    tag: str,
    source_commit: str,
    owner_run_id: int,
    owner_run_attempt: int,
    owner_head_sha: str,
) -> dict[str, object]:
    """Verify Release and workflow-run identity against independent GitHub reads.

    Must be rerun immediately before any eventual write; orchestration must
    separately provide exclusive writer serialization for the full lifecycle.
    """
    _valid_inputs(repo, release_id, tag, source_commit)
    if owner_head_sha != source_commit:
        raise ValueError("owner main commit differs from protected release source")

    if _TAG.fullmatch(tag) is None:
        raise ValueError("unsupported release tag")

    verify_active_owner_run(
        client,
        repo=repo,
        owner_run_id=owner_run_id,
        owner_run_attempt=owner_run_attempt,
        owner_head_sha=owner_head_sha,
    )
    verify_tag_protection(client, repo, tag)
    release = client.release(repo, release_id)
    if (
        not isinstance(release, dict)
        or type(release.get("id")) is not int
        or release["id"] != release_id
    ):
        raise ValueError("GitHub release ID differs from requested target")
    _draft_release(release, repo, tag, source_commit, client.tag_commit(repo, tag))
    return {
        "identityVerified": True,
        "tagProtectionVerified": True,
        "repository": repo,
        "releaseId": release_id,
        "tag": tag,
        "sourceCommit": source_commit,
        "ownerRunId": owner_run_id,
        "ownerRunAttempt": owner_run_attempt,
        "ownerHeadSha": owner_head_sha,
        # No API field can attest the Actions concurrency group or lock owner.
        "exclusiveWriterVerified": False,
        "publicationAuthorized": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--release-id", required=True, type=int)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--owner-run-id", required=True, type=int)
    parser.add_argument("--owner-run-attempt", required=True, type=int)
    parser.add_argument("--owner-head-sha", required=True)
    args = parser.parse_args()
    try:
        result = verify_owner(
            OwnerGitHubCLI(),
            repo=args.repo,
            release_id=args.release_id,
            tag=args.tag,
            source_commit=args.source_commit,
            owner_run_id=args.owner_run_id,
            owner_run_attempt=args.owner_run_attempt,
            owner_head_sha=args.owner_head_sha,
        )
    except (ValueError, OSError) as exc:
        parser.exit(2, f"draft Release owner verification: FAIL: {exc}\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

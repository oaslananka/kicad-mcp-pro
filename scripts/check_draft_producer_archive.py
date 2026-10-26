"""Verify a downloaded Actions artifact ZIP against current GitHub API metadata.

This only checks read-only run/archive identity and digest. A matching archive
is NOT proof of the individual producing job, signed attestation or publishing
authority. Strictly accepts completed successful main workflow_dispatch runs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Protocol

from scripts.runtime_path_safety import approved_runtime_path

REPOSITORY = "oaslananka/kicad-mcp-pro"
_SHA = re.compile(r"^[0-9a-f]{40}$")
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_ARTIFACT_WORKFLOWS: dict[str, set[str]] = {
    "python-dist": {".github/workflows/publish-python.yml"},
    "python-release-evidence": {".github/workflows/publish-python.yml"},
    "mcpb-release-evidence": {".github/workflows/publish-mcpb.yml"},
    "kicad-pcm-release-evidence": {".github/workflows/publish-kicad-pcm.yml"},
}

# Only the single read-only dispatcher may be a reusable-producer run.
# This is run/archive binding, not proof of the individual called job.
_REUSABLE_CALLER_WORKFLOW = ".github/workflows/draft-producer-preflight.yml"
_REUSABLE_ARTIFACT_WORKFLOWS: dict[str, set[str]] = {
    "python-dist": {_REUSABLE_CALLER_WORKFLOW},
    "python-release-evidence": {_REUSABLE_CALLER_WORKFLOW},
    "mcpb-release-evidence": {_REUSABLE_CALLER_WORKFLOW},
    "kicad-pcm-release-evidence": {_REUSABLE_CALLER_WORKFLOW},
    "protocol-schemas-release-evidence": {_REUSABLE_CALLER_WORKFLOW},
}


def _approved_role_workflows(profile: str) -> dict[str, set[str]]:
    """Never broaden legacy trust roots to the new caller implicitly."""
    if profile == "legacy":
        return _ARTIFACT_WORKFLOWS
    if profile == "reusable":
        return _REUSABLE_ARTIFACT_WORKFLOWS
    raise ValueError("unapproved producer profile")


class ReadOnlyArtifactClient(Protocol):
    def workflow_run(self, repo: str, run_id: int) -> dict[str, Any]: ...

    def artifact(self, repo: str, artifact_id: int) -> dict[str, Any]: ...


class GitHubArtifactClient:
    """Read-only gh api calls; no artifact downloads or GitHub writes."""

    def _get(self, route: str) -> dict[str, Any]:
        gh_binary = shutil.which("gh")
        if gh_binary is None:
            raise ValueError("GitHub CLI not available")
        result = subprocess.run(
            [gh_binary, "api", route],
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        )
        payload = json.loads(result.stdout)
        if not isinstance(payload, dict):
            raise ValueError("GitHub returned non-object JSON")
        return payload

    def workflow_run(self, repo: str, run_id: int) -> dict[str, Any]:
        return self._get(f"repos/{repo}/actions/runs/{run_id}")

    def artifact(self, repo: str, artifact_id: int) -> dict[str, Any]:
        return self._get(f"repos/{repo}/actions/artifacts/{artifact_id}")


def _verify_run(
    run: object,
    *,
    repo: str,
    run_id: int,
    attempt: int,
    head_sha: str,
    role: str,
    producer_profile: str = "legacy",
) -> int:
    workflows = _approved_role_workflows(producer_profile)
    if role not in workflows:
        raise ValueError("unapproved producer profile or artifact role")
    if not isinstance(run, dict):
        raise ValueError("invalid GitHub workflow run")
    r = run.get("repository")
    h = run.get("head_repository")
    if not isinstance(r, dict) or not isinstance(h, dict):
        raise ValueError("missing GitHub repository identity")
    repo_id = r.get("id")
    if (
        type(run.get("id")) is not int
        or run["id"] != run_id
        or run.get("url") != f"https://api.github.com/repos/{repo}/actions/runs/{run_id}"
        or r.get("full_name") != repo
        or h.get("full_name") != repo
        or type(repo_id) is not int
        or repo_id <= 0
        or h.get("id") != repo_id
    ):
        raise ValueError("workflow run repository or ID mismatch")
    if (
        run.get("path") not in workflows[role]
        or run.get("event") != "workflow_dispatch"
        or run.get("head_branch") != "main"
        or run.get("head_sha") != head_sha
        or run.get("status") != "completed"
        or run.get("conclusion") != "success"
        or type(run.get("run_attempt")) is not int
        or run["run_attempt"] != attempt
    ):
        raise ValueError("workflow run was not an approved completed main producer")
    return repo_id


def _verify_artifact(
    artifact: object,
    *,
    repo: str,
    repo_id: int,
    run_id: int,
    head_sha: str,
    artifact_id: int,
    role: str,
) -> str:
    if not isinstance(artifact, dict):
        raise ValueError("invalid GitHub artifact metadata")
    run = artifact.get("workflow_run")
    if not isinstance(run, dict):
        raise ValueError("artifact lacks workflow-run identity")
    digest = artifact.get("digest")
    if (
        type(artifact.get("id")) is not int
        or artifact["id"] != artifact_id
        or artifact.get("name") != role
        or artifact.get("expired") is not False
        or type(artifact.get("size_in_bytes")) is not int
        or artifact["size_in_bytes"] <= 0
        or not isinstance(digest, str)
        or _DIGEST.fullmatch(digest) is None
        or artifact.get("url")
        != f"https://api.github.com/repos/{repo}/actions/artifacts/{artifact_id}"
        or artifact.get("archive_download_url")
        != f"https://api.github.com/repos/{repo}/actions/artifacts/{artifact_id}/zip"
    ):
        raise ValueError("wrong, expired or missing-digest GitHub Actions artifact")
    if (
        run.get("id") != run_id
        or type(run.get("id")) is not int
        or run.get("repository_id") != repo_id
        or run.get("head_repository_id") != repo_id
        or run.get("head_branch") != "main"
        or run.get("head_sha") != head_sha
    ):
        raise ValueError("artifact belongs to a different workflow run or repository")
    return digest[7:]


def verify_archive(
    client: ReadOnlyArtifactClient,
    *,
    repo: str,
    role: str,
    run_id: int,
    run_attempt: int,
    artifact_id: int,
    head_sha: str,
    downloaded_zip: Path,
    producer_profile: str = "legacy",
) -> dict[str, object]:
    """Conservative run/archive identity only; no signed job or publish authority."""
    workflows = _approved_role_workflows(producer_profile)
    if (
        repo != REPOSITORY
        or role not in workflows
        or any(type(value) is not int or value <= 0 for value in (run_id, run_attempt, artifact_id))
        or _SHA.fullmatch(head_sha) is None
    ):
        raise ValueError("unapproved workflow artifact identity")
    if downloaded_zip.is_symlink():
        raise ValueError("downloaded Actions ZIP must not be a symlink")
    path = approved_runtime_path(downloaded_zip)
    if not path.is_file() or not path.stat().st_size:
        raise ValueError("missing or empty downloaded Actions ZIP")

    run = client.workflow_run(repo, run_id)
    repo_id = _verify_run(
        run,
        repo=repo,
        run_id=run_id,
        attempt=run_attempt,
        head_sha=head_sha,
        role=role,
        producer_profile=producer_profile,
    )
    artifact = client.artifact(repo, artifact_id)
    expected_digest = _verify_artifact(
        artifact,
        repo=repo,
        repo_id=repo_id,
        run_id=run_id,
        head_sha=head_sha,
        artifact_id=artifact_id,
        role=role,
    )
    hasher = hashlib.sha256()
    with path.open("rb") as inp:
        for block in iter(lambda: inp.read(1024 * 1024), b""):
            hasher.update(block)
    if hasher.hexdigest() != expected_digest:
        raise ValueError("downloaded ZIP differs from GitHub artifact SHA256")
    # Re-read live metadata to reduce a stale/replaced record race.
    repeat = client.artifact(repo, artifact_id)
    if repeat != artifact:
        raise ValueError("GitHub Actions artifact metadata changed during verification")
    return {
        "repo": repo,
        "role": role,
        "producerProfile": producer_profile,
        "runId": run_id,
        "runAttempt": run_attempt,
        "artifactId": artifact_id,
        "headSha": head_sha,
        "archiveSha256": expected_digest,
        "workflowRunIdentityVerified": True,
        "reusableCallerWorkflowVerified": producer_profile == "reusable",
        "artifactArchiveDigestVerified": True,
        "producerJobIdentityVerified": False,
        "signedAttestationVerified": False,
        "registryReceiptVerified": False,
        "publicationAuthorized": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--role", required=True)
    parser.add_argument(
        "--producer-profile",
        default="legacy",
        choices=("legacy", "reusable"),
        help="Exact standalone publish or draft-producer caller workflow identity",
    )
    parser.add_argument("--run-id", type=int, required=True)
    parser.add_argument("--run-attempt", type=int, required=True)
    parser.add_argument("--artifact-id", type=int, required=True)
    parser.add_argument("--head-sha", required=True)
    parser.add_argument("--downloaded-zip", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = verify_archive(
            GitHubArtifactClient(),
            repo=args.repo,
            role=args.role,
            run_id=args.run_id,
            run_attempt=args.run_attempt,
            artifact_id=args.artifact_id,
            head_sha=args.head_sha,
            downloaded_zip=args.downloaded_zip,
            producer_profile=args.producer_profile,
        )
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        parser.exit(2, f"draft producer ZIP gate: FAIL: {exc}\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

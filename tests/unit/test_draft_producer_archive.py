"""Offline fixture tests for Actions run/artifact identity and ZIP digest gate."""

from __future__ import annotations

import hashlib
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from scripts.check_draft_producer_archive import (
    _ARTIFACT_WORKFLOWS,
    REPOSITORY,
    verify_archive,
)

SHA = "a" * 40
RUN_ID = 991122
ATTEMPT = 1
ARTIFACT_ID = 778899
REPO_ID = 12345
ROLE = "mcpb-release-evidence"
ZIP_BYTES = b"fixture archived artifact bytes"


class FakeClient:
    def __init__(self, role: str = ROLE) -> None:
        self.role = role
        self.run: dict[str, Any] = {
            "id": RUN_ID,
            "url": f"https://api.github.com/repos/{REPOSITORY}/actions/runs/{RUN_ID}",
            "repository": {"id": REPO_ID, "full_name": REPOSITORY},
            "head_repository": {"id": REPO_ID, "full_name": REPOSITORY},
            "path": next(iter(_ARTIFACT_WORKFLOWS[role])),
            "event": "workflow_dispatch",
            "head_branch": "main",
            "head_sha": SHA,
            "run_attempt": ATTEMPT,
            "status": "completed",
            "conclusion": "success",
        }
        self.art: dict[str, Any] = {
            "id": ARTIFACT_ID,
            "name": role,
            "expired": False,
            "size_in_bytes": len(ZIP_BYTES),
            "digest": f"sha256:{hashlib.sha256(ZIP_BYTES).hexdigest()}",
            "url": f"https://api.github.com/repos/{REPOSITORY}/actions/artifacts/{ARTIFACT_ID}",
            "archive_download_url": (
                f"https://api.github.com/repos/{REPOSITORY}/actions/artifacts/{ARTIFACT_ID}/zip"
            ),
            "workflow_run": {
                "id": RUN_ID,
                "repository_id": REPO_ID,
                "head_repository_id": REPO_ID,
                "head_branch": "main",
                "head_sha": SHA,
            },
        }
        self.changed_after_first_artifact_read = False
        self.artifact_reads = 0

    def workflow_run(self, repo: str, run_id: int) -> dict[str, Any]:
        assert repo == REPOSITORY
        assert run_id == RUN_ID
        return deepcopy(self.run)

    def artifact(self, repo: str, artifact_id: int) -> dict[str, Any]:
        assert repo == REPOSITORY
        assert artifact_id == ARTIFACT_ID
        self.artifact_reads += 1
        result = deepcopy(self.art)
        if self.changed_after_first_artifact_read and self.artifact_reads > 1:
            result["expired"] = True
        return result


def _case(tmp_path: Path, role: str = ROLE) -> tuple[FakeClient, dict[str, Any]]:
    zip_path = tmp_path / "downloaded.zip"
    zip_path.write_bytes(ZIP_BYTES)
    return FakeClient(role), {
        "repo": REPOSITORY,
        "role": role,
        "run_id": RUN_ID,
        "run_attempt": ATTEMPT,
        "artifact_id": ARTIFACT_ID,
        "head_sha": SHA,
        "downloaded_zip": zip_path,
    }


@pytest.mark.parametrize(
    "role",
    [
        "python-dist",
        "python-release-evidence",
        "mcpb-release-evidence",
        "kicad-pcm-release-evidence",
    ],
)
def test_approved_artifact_roles_match_git_hub_zip_digest(tmp_path: Path, role: str) -> None:
    client, kwargs = _case(tmp_path, role)
    result = verify_archive(client, **kwargs)
    assert result["workflowRunIdentityVerified"] is True
    assert result["artifactArchiveDigestVerified"] is True
    assert result["producerJobIdentityVerified"] is False
    assert result["signedAttestationVerified"] is False
    assert result["publicationAuthorized"] is False
    assert client.artifact_reads == 2


@pytest.mark.parametrize(
    ("section", "field", "value"),
    [
        ("run", "path", ".github/workflows/unrelated.yml"),
        ("run", "event", "pull_request"),
        ("run", "head_branch", "unprotected-branch"),
        ("run", "head_sha", "b" * 40),
        ("run", "status", "in_progress"),
        ("run", "conclusion", "failure"),
        ("run", "run_attempt", 2),
        ("run", "url", "https://api.github.com/repos/foreign/repo/actions/runs/991122"),
        ("art", "name", "another-artifact"),
        ("art", "digest", None),
        ("art", "digest", "sha256:not-a-hash"),
        ("art", "expired", True),
        ("art", "size_in_bytes", 0),
        ("art", "archive_download_url", "https://attacker.example/artifact.zip"),
    ],
)
def test_wrong_run_or_artifact_identity_rejected(
    tmp_path: Path, section: str, field: str, value: object
) -> None:
    client, kwargs = _case(tmp_path)
    getattr(client, section)[field] = value
    with pytest.raises(ValueError):
        verify_archive(client, **kwargs)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("id", ARTIFACT_ID + 1),
        ("repository_id", REPO_ID + 1),
        ("head_repository_id", REPO_ID + 1),
        ("head_branch", "feature-branch"),
        ("head_sha", "b" * 40),
    ],
)
def test_artifact_workflow_linkage_rejected(tmp_path: Path, field: str, value: object) -> None:
    client, kwargs = _case(tmp_path)
    client.art["workflow_run"][field] = value
    with pytest.raises(ValueError, match="different workflow run"):
        verify_archive(client, **kwargs)


def test_release_owner_workflow_cannot_masquerade_as_family_producer(tmp_path: Path) -> None:
    client, kwargs = _case(tmp_path, "mcpb-release-evidence")
    client.run["path"] = ".github/workflows/publish-release.yml"
    with pytest.raises(ValueError, match="approved completed main producer"):
        verify_archive(client, **kwargs)


def test_tampered_download_is_rejected(tmp_path: Path) -> None:
    client, kwargs = _case(tmp_path)
    kwargs["downloaded_zip"].write_bytes(b"different zip bytes")
    with pytest.raises(ValueError, match="ZIP differs"):
        verify_archive(client, **kwargs)


def test_changed_remote_artifact_identity_rejected(tmp_path: Path) -> None:
    client, kwargs = _case(tmp_path)
    client.changed_after_first_artifact_read = True
    with pytest.raises(ValueError, match="metadata changed"):
        verify_archive(client, **kwargs)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("role", "unknown-artifact"),
        ("repo", "foreign/repository"),
        ("head_sha", "invalid"),
        ("run_id", True),
        ("run_attempt", 0),
        ("artifact_id", -1),
    ],
)
def test_invalid_requested_identity_rejected_without_network(
    tmp_path: Path, field: str, value: object
) -> None:
    client, kwargs = _case(tmp_path)
    kwargs[field] = value
    with pytest.raises(ValueError, match="unapproved"):
        verify_archive(client, **kwargs)
    assert client.artifact_reads == 0


def test_symlink_zip_is_rejected(tmp_path: Path) -> None:
    client, kwargs = _case(tmp_path)
    other = tmp_path / "actual.zip"
    other.write_bytes(ZIP_BYTES)
    kwargs["downloaded_zip"].unlink()
    try:
        kwargs["downloaded_zip"].symlink_to(other)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation is unavailable on this platform")
    with pytest.raises(ValueError, match="symlink"):
        verify_archive(client, **kwargs)


def test_mismatched_repository_identifiers_are_rejected(tmp_path: Path) -> None:
    client, kwargs = _case(tmp_path)
    client.run["head_repository"]["id"] = REPO_ID + 5
    with pytest.raises(ValueError, match="repository"):
        verify_archive(client, **kwargs)

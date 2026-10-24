"""Offline adversarial tests for read-only #1179 owner-run preflight."""

from __future__ import annotations

import copy
from typing import Any

import pytest

from scripts.check_draft_release_owner import verify_owner

REPO = "oaslananka/kicad-mcp-pro"
TAG = "mcp-server-v4.4.0"
SOURCE = "a" * 40
HEAD = SOURCE
RUN = 98765
RELEASE = 42


class FakeOwnerClient:
    def __init__(self) -> None:
        self.run_data: dict[str, Any] = {
            "id": RUN,
            "url": f"https://api.github.com/repos/{REPO}/actions/runs/{RUN}",
            "repository": {"full_name": REPO},
            "head_repository": {"full_name": REPO},
            "path": ".github/workflows/publish-release.yml",
            "event": "workflow_dispatch",
            "head_branch": "main",
            "head_sha": HEAD,
            "run_attempt": 2,
            "status": "in_progress",
            "conclusion": None,
        }
        self.release_data: dict[str, Any] = {
            "id": RELEASE,
            "url": f"https://api.github.com/repos/{REPO}/releases/{RELEASE}",
            "tag_name": TAG,
            "draft": True,
            "published_at": None,
            "assets": [],
        }
        self.tag_sha = SOURCE
        self.calls: list[str] = []

    def workflow_run(self, repo: str, run_id: int) -> dict[str, Any]:
        self.calls.append("run")
        assert repo == REPO
        assert run_id == RUN
        return copy.deepcopy(self.run_data)

    def release(self, repo: str, release_id: int) -> dict[str, Any]:
        self.calls.append("release")
        assert repo == REPO
        assert release_id == RELEASE
        return copy.deepcopy(self.release_data)

    def tag_commit(self, repo: str, tag: str) -> str:
        self.calls.append("tag")
        assert repo == REPO
        assert tag == TAG
        return self.tag_sha


def _args() -> dict[str, Any]:
    return {
        "repo": REPO,
        "release_id": RELEASE,
        "tag": TAG,
        "source_commit": SOURCE,
        "owner_run_id": RUN,
        "owner_run_attempt": 2,
        "owner_head_sha": HEAD,
    }


def test_valid_read_only_owner_preflight() -> None:
    client = FakeOwnerClient()
    result = verify_owner(client, **_args())
    assert result["identityVerified"] is True
    assert result["releaseId"] == RELEASE
    assert result["ownerRunAttempt"] == 2
    assert result["exclusiveWriterVerified"] is False
    assert result["publicationAuthorized"] is False
    assert client.calls == ["run", "release", "tag"]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("id", 100),
        ("id", True),
        ("url", "https://api.github.com/repos/foreign/repo/actions/runs/98765"),
        ("repository", {"full_name": "other/repo"}),
        ("repository", None),
        ("head_repository", {"full_name": "other/repo"}),
        ("head_repository", None),
        ("path", ".github/workflows/untrusted.yml"),
        ("event", "pull_request_target"),
        ("event", "push"),
        ("head_branch", "feature"),
        ("head_sha", "b" * 40),
        ("run_attempt", 1),
        ("run_attempt", True),
        ("status", "completed"),
        ("status", "queued"),
        ("conclusion", "success"),
    ],
)
def test_invalid_owner_run_fails_before_release_access(field: str, value: object) -> None:
    client = FakeOwnerClient()
    client.run_data[field] = value
    args = _args()
    with pytest.raises(ValueError, match="workflow run"):
        verify_owner(client, **args)
    assert client.calls == ["run"]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("id", 43),
        ("id", True),
        ("url", "https://api.github.com/repos/other/repo/releases/42"),
        ("tag_name", "other-v1"),
        ("draft", False),
        ("published_at", "2026-10-24T00:00:00Z"),
    ],
)
def test_invalid_release_identity_fails_closed(field: str, value: object) -> None:
    client = FakeOwnerClient()
    client.release_data[field] = value
    args = _args()
    with pytest.raises(ValueError, match="release|Release"):
        verify_owner(client, **args)


def test_unrelated_main_workflow_cannot_adopt_other_draft() -> None:
    client = FakeOwnerClient()
    args = {**_args(), "owner_head_sha": "b" * 40}
    with pytest.raises(ValueError, match="owner main commit"):
        verify_owner(client, **args)
    assert client.calls == []


def test_tag_changed_fails_closed() -> None:
    client = FakeOwnerClient()
    client.tag_sha = "b" * 40
    args = _args()
    with pytest.raises(ValueError, match="tag"):
        verify_owner(client, **args)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("repo", "invalid"),
        ("release_id", -1),
        ("release_id", True),
        ("tag", "bad/tag"),
        ("source_commit", "1"),
        ("owner_run_id", 0),
        ("owner_run_id", True),
        ("owner_run_attempt", 0),
        ("owner_run_attempt", True),
        ("owner_head_sha", "short"),
    ],
)
def test_invalid_cli_identity_never_queries_api(field: str, value: object) -> None:
    client = FakeOwnerClient()
    args = _args()
    args[field] = value
    with pytest.raises(ValueError):
        verify_owner(client, **args)
    assert not client.calls

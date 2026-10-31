"""Adversarial, entirely offline draft-owner readiness checks (#1179)."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from scripts.check_draft_release_owner_readiness import check_readiness

REPO = "oaslananka/kicad-mcp-pro"
TAG = "mcp-npm-v4.4.0"
SHA = "a" * 40
RUN = 1287
RELEASE_ID = 42
NAMES = [
    "kicad-mcp-pro-4.4.0.tgz",
    "mcp-npm-SHA256SUMS.txt",
    "mcp-npm-sbom.cdx.json",
    "npm-published-digest.json",
]


class FakeClient:
    def __init__(self, assets: list[dict[str, Any]], content: dict[int, bytes]) -> None:
        self.content = content
        self.run = {
            "id": RUN,
            "url": f"https://api.github.com/repos/{REPO}/actions/runs/{RUN}",
            "repository": {"full_name": REPO},
            "head_repository": {"full_name": REPO},
            "path": ".github/workflows/publish-release.yml",
            "event": "workflow_dispatch",
            "actor": {"login": "oaslananka"},
            "triggering_actor": {"login": "oaslananka"},
            "head_branch": "main",
            "head_sha": SHA,
            "run_attempt": 1,
            "status": "in_progress",
            "conclusion": None,
        }
        self.release_data = {
            "id": RELEASE_ID,
            "url": f"https://api.github.com/repos/{REPO}/releases/{RELEASE_ID}",
            "tag_name": TAG,
            "draft": True,
            "published_at": None,
            "assets": assets,
        }
        self.tag_sha = SHA
        self.requests: list[str] = []
        self.late_published = False
        self.late_owner_completed = False

    def workflow_run(self, repo: str, run_id: int) -> dict[str, Any]:
        assert repo == REPO
        assert run_id == RUN
        self.requests.append("run")
        result = copy.deepcopy(self.run)
        if self.late_owner_completed and self.requests.count("run") >= 2:
            result["status"] = "completed"
            result["conclusion"] = "success"
        return result

    def release(self, repo: str, release_id: int) -> dict[str, Any]:
        assert repo == REPO
        assert release_id == RELEASE_ID
        self.requests.append("release")
        result = copy.deepcopy(self.release_data)
        if self.late_published and self.requests.count("release") >= 3:
            result["draft"] = False
            result["published_at"] = "2026-10-25T00:00:00Z"
        return result

    def tag_commit(self, repo: str, tag: str) -> str:
        assert repo == REPO
        assert tag == TAG
        self.requests.append("tag")
        return self.tag_sha

    def download_asset(self, repo: str, asset_id: int, destination: Path) -> None:
        assert repo == REPO
        self.requests.append("download")
        destination.write_bytes(self.content[asset_id])

    def upload_asset(self, repo: str, release_id: int, path: Path) -> None:
        raise AssertionError("read-only owner readiness must never upload")


def _setup(tmp_path: Path) -> tuple[FakeClient, dict[str, Any]]:
    assets = []
    remote_content: dict[int, bytes] = {}
    for asset_id, name in enumerate(NAMES, start=1):
        content = f"fixture: {name}".encode()
        sha = hashlib.sha256(content).hexdigest()
        remote_content[asset_id] = content
        assets.append({"name": name, "id": asset_id, "size": len(content), "sha256": sha})
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "releaseTag": TAG,
                "sourceCommit": SHA,
                "assets": assets,
            }
        )
    )
    remote = [
        {
            "name": a["name"],
            "id": a["id"],
            "size": a["size"],
            "digest": f"sha256:{a['sha256']}",
            "state": "uploaded",
        }
        for a in assets
    ]
    return FakeClient(remote, remote_content), {
        "manifest_path": manifest,
        "manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
        "repo": REPO,
        "release_id": RELEASE_ID,
        "tag": TAG,
        "source_commit": SHA,
        "owner_run_id": RUN,
        "owner_run_attempt": 1,
        "owner_head_sha": SHA,
    }


def _remove_manifest_asset(args: dict[str, Any], name: str) -> None:
    path = args["manifest_path"]
    doc = json.loads(path.read_text())
    doc["assets"] = [asset for asset in doc["assets"] if asset["name"] != name]
    path.write_text(json.dumps(doc))
    args["manifest_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()


def test_complete_draft_verifies_all_three_layers_but_never_authorizes(
    tmp_path: Path,
) -> None:
    client, args = _setup(tmp_path)
    result = check_readiness(client, **args)
    assert result["familyAssetNamesVerified"] is True
    assert result["ownerIdentityVerified"] is True
    assert result["draftAssetsVerified"] is True
    assert result["assetCount"] == 4
    assert result["exclusiveWriterVerified"] is False
    assert result["registriesVerified"] is False
    assert result["attestationsVerified"] is False
    assert result["publicationAuthorized"] is False
    assert client.requests == [
        "run",
        "release",
        "tag",
        "release",
        "tag",
        "download",
        "download",
        "download",
        "download",
        "run",
        "release",
        "tag",
        "release",
    ]


@pytest.mark.parametrize("name", NAMES)
def test_missing_family_role_rejected_before_api(tmp_path: Path, name: str) -> None:
    client, args = _setup(tmp_path)
    _remove_manifest_asset(args, name)
    with pytest.raises(ValueError, match="incomplete release family"):
        check_readiness(client, **args)
    assert client.requests == []


def test_manifest_digest_mismatch_prevents_api_call(tmp_path: Path) -> None:
    client, args = _setup(tmp_path)
    args["manifest_sha256"] = "b" * 64
    with pytest.raises(ValueError, match="trusted manifest"):
        check_readiness(client, **args)
    assert client.requests == []


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("head_sha", "b" * 40),
        ("path", ".github/workflows/untrusted.yml"),
        ("run_attempt", 2),
        ("status", "completed"),
        ("event", "pull_request"),
    ],
)
def test_invalid_owner_run_rejected_before_asset_access(
    tmp_path: Path, field: str, value: object
) -> None:
    client, args = _setup(tmp_path)
    client.run[field] = value
    with pytest.raises(ValueError, match="workflow run"):
        check_readiness(client, **args)
    assert client.requests == ["run"]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("draft", False),
        ("tag_name", "mcp-npm-v99.0.0"),
        ("id", 43),
        ("published_at", "2026-10-25T00:00:00Z"),
    ],
)
def test_invalid_draft_identity_rejected(tmp_path: Path, field: str, value: object) -> None:
    client, args = _setup(tmp_path)
    client.release_data[field] = value
    with pytest.raises(ValueError, match="release|Release"):
        check_readiness(client, **args)


def test_wrong_protected_tag_commit_rejected(tmp_path: Path) -> None:
    client, args = _setup(tmp_path)
    client.tag_sha = "b" * 40
    with pytest.raises(ValueError, match="tag"):
        check_readiness(client, **args)


def test_remote_asset_mismatch_rejected(tmp_path: Path) -> None:
    client, args = _setup(tmp_path)
    client.release_data["assets"][0]["digest"] = "sha256:" + "b" * 64
    with pytest.raises(ValueError, match="GitHub draft asset digest"):
        check_readiness(client, **args)


def test_downloaded_bytes_tampered_rejected(tmp_path: Path) -> None:
    client, args = _setup(tmp_path)
    client.content[1] = b"attacker bytes"
    with pytest.raises(ValueError, match="downloaded draft asset"):
        check_readiness(client, **args)


def test_downloaded_file_missing_rejected(tmp_path: Path) -> None:
    client, args = _setup(tmp_path)
    client.release_data["assets"].pop(0)
    with pytest.raises(ValueError, match="draft release assets differ"):
        check_readiness(client, **args)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("id", RELEASE_ID + 1),
        ("tag_name", "mcp-npm-v99.0.0"),
        ("draft", False),
        ("url", f"https://api.github.com/repos/{REPO}/releases/{RELEASE_ID + 1}"),
    ],
)
def test_midpoint_release_identity_rejected_before_download(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, field: str, value: object
) -> None:
    """The independent asset read may not switch drafts between owner checks."""
    client, args = _setup(tmp_path)
    original_release = client.release

    def swapped_release(repo: str, release_id: int) -> dict[str, Any]:
        result = original_release(repo, release_id)
        if client.requests.count("release") == 2:
            result[field] = value
            if field == "id":
                result["url"] = f"https://api.github.com/repos/{REPO}/releases/{value}"
        return result

    monkeypatch.setattr(client, "release", swapped_release)
    with pytest.raises(ValueError, match="draft|release|Release"):
        check_readiness(client, **args)
    assert "download" not in client.requests


def test_publication_between_reads_rejected(tmp_path: Path) -> None:
    client, args = _setup(tmp_path)
    client.late_published = True
    with pytest.raises(ValueError, match="release"):
        check_readiness(client, **args)


@pytest.mark.parametrize(
    "field,value", [("release_id", True), ("owner_run_id", 0), ("tag", "mcp-npm-v4.4.0-alpha")]
)
def test_invalid_owner_arguments_rejected(tmp_path: Path, field: str, value: object) -> None:
    client, args = _setup(tmp_path)
    args[field] = value
    with pytest.raises(ValueError):
        check_readiness(client, **args)


def test_owner_finishes_during_remote_download_fails_closed(tmp_path: Path) -> None:
    client, args = _setup(tmp_path)
    client.late_owner_completed = True
    with pytest.raises(ValueError, match="workflow run"):
        check_readiness(client, **args)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("id", 0),
        ("id", True),
        ("id", 1),
        ("state", "starter"),
    ],
)
def test_invalid_remote_asset_id_or_state_rejected(
    tmp_path: Path, field: str, value: object
) -> None:
    client, args = _setup(tmp_path)
    client.release_data["assets"][1][field] = value
    with pytest.raises(ValueError, match="asset"):
        check_readiness(client, **args)


def test_duplicate_remote_asset_id_rejected(tmp_path: Path) -> None:
    client, args = _setup(tmp_path)
    client.release_data["assets"][1]["id"] = client.release_data["assets"][0]["id"]
    with pytest.raises(ValueError, match="duplicate"):
        check_readiness(client, **args)


def test_unapproved_remote_asset_cannot_be_downloaded(tmp_path: Path) -> None:
    client, args = _setup(tmp_path)
    client.release_data["assets"].append(
        {"id": 123, "name": "stranger.zip", "size": 3, "state": "uploaded"}
    )
    with pytest.raises(ValueError, match="unknown"):
        check_readiness(client, **args)
    assert "download" not in client.requests


def test_remote_asset_download_error_fails_closed(tmp_path: Path) -> None:
    client, args = _setup(tmp_path)
    del client.content[1]
    with pytest.raises(KeyError):
        check_readiness(client, **args)


@pytest.mark.parametrize("mutation", ["replacement-id", "altered-digest", "extra-asset"])
def test_inventory_changes_after_verified_download_are_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: str
) -> None:
    """Owner remains valid, but an asset changes at the final inventory read."""
    client, args = _setup(tmp_path)
    original_release = client.release

    def racing_release(repo: str, release_id: int) -> dict[str, Any]:
        release = original_release(repo, release_id)
        if client.requests.count("release") >= 4:
            if mutation == "replacement-id":
                release["assets"][0]["id"] = 999
            elif mutation == "altered-digest":
                release["assets"][0]["digest"] = "sha256:" + "b" * 64
            else:
                release["assets"].append(
                    {"id": 999, "name": "unexpected.zip", "state": "uploaded", "size": 1}
                )
        return release

    monkeypatch.setattr(client, "release", racing_release)
    with pytest.raises(ValueError, match="inventory changed"):
        check_readiness(client, **args)


def test_final_draft_read_ignores_order_and_download_counts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, args = _setup(tmp_path)
    original_release = client.release

    def reordered_release(repo: str, release_id: int) -> dict[str, Any]:
        release = original_release(repo, release_id)
        if client.requests.count("release") >= 4:
            release["assets"].reverse()
            for asset in release["assets"]:
                asset["download_count"] = 42
        return release

    monkeypatch.setattr(client, "release", reordered_release)
    result = check_readiness(client, **args)
    assert result["draftAssetsVerified"] is True
    assert result["publicationAuthorized"] is False

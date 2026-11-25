"""Legacy published releases: add missing bytes, never replace existing evidence."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pytest

from scripts.attach_published_release_assets import attach

REPO = "oaslananka/kicad-mcp-pro"
TAG = "mcp-server-v4.22.6"
SHA = "a" * 40


class FakeGitHub:
    def __init__(self) -> None:
        self.assets: dict[str, tuple[int, bytes]] = {"other-family.zip": (1, b"other")}
        self.uploads: list[str] = []
        self.downloads: list[int] = []
        self.draft = False
        self.immutable = False
        self.tag_sha = SHA
        self.release_id = 42
        self.fail_name = ""

    def release_by_tag(self, repo: str, tag: str) -> dict[str, Any]:
        return self.release(repo, self.release_id)

    def release(self, repo: str, release_id: int) -> dict[str, Any]:
        return {
            "id": self.release_id,
            "url": f"https://api.github.com/repos/{repo}/releases/{self.release_id}",
            "tag_name": TAG,
            "draft": self.draft,
            "published_at": "2026-11-25T00:00:00Z",
            "immutable": self.immutable,
            "assets": [
                {
                    "id": identity,
                    "name": name,
                    "state": "uploaded",
                    "size": len(data),
                    "digest": "sha256:" + hashlib.sha256(data).hexdigest(),
                }
                for name, (identity, data) in self.assets.items()
            ],
        }

    def tag_commit(self, repo: str, tag: str) -> str:
        return self.tag_sha

    def download_asset(self, repo: str, asset_id: int, destination: Path) -> None:
        self.downloads.append(asset_id)
        destination.write_bytes(
            next(data for identity, data in self.assets.values() if identity == asset_id)
        )

    def upload_asset(self, repo: str, release_id: int, path: Path) -> None:
        assert release_id == self.release_id
        assert path.name not in self.assets
        if path.name == self.fail_name:
            raise ValueError("interrupted upload")
        self.uploads.append(path.name)
        self.assets[path.name] = (
            max(identity for identity, _ in self.assets.values()) + 1,
            path.read_bytes(),
        )


@pytest.fixture
def assets(tmp_path: Path) -> list[Path]:
    result = [tmp_path / name for name in ("a.whl", "b.json")]
    for path in result:
        path.write_bytes(path.name.encode())
    return result


def _attach(client: FakeGitHub, paths: list[Path], *, execute: bool = True) -> dict[str, object]:
    return attach(
        client,
        repo=REPO,
        tag=TAG,
        source_commit=SHA,
        source_root=paths[0].parent,
        paths=paths,
        execute=execute,
    )


def test_partial_retry_preserves_identity_and_unrelated_family(assets: list[Path]) -> None:
    client = FakeGitHub()
    client.assets["a.whl"] = (2, assets[0].read_bytes())
    result = _attach(client, assets)
    assert result["uploaded"] == ["b.json"]
    assert result["preserved"] == ["a.whl"]
    assert client.assets["a.whl"][0] == 2
    assert client.assets["other-family.zip"] == (1, b"other")
    assert 2 in client.downloads
    assert _attach(client, assets)["uploaded"] == []
    assert client.uploads == ["b.json"]


def test_conflict_before_first_upload(assets: list[Path]) -> None:
    client = FakeGitHub()
    client.assets["b.json"] = (2, b"different")
    with pytest.raises(ValueError, match="bytes|digest|size"):
        _attach(client, assets)
    assert client.uploads == []


def test_interruption_can_resume_without_overwrite(assets: list[Path]) -> None:
    client = FakeGitHub()
    client.fail_name = "b.json"
    with pytest.raises(ValueError, match="interrupted"):
        _attach(client, assets)
    original = client.assets["a.whl"]
    client.fail_name = ""
    assert _attach(client, assets)["uploaded"] == ["b.json"]
    assert client.assets["a.whl"] == original


@pytest.mark.parametrize("reason", ["draft", "immutable", "wrong-tag", "duplicate-id"])
def test_rejects_unsafe_release_before_mutation(assets: list[Path], reason: str) -> None:
    client = FakeGitHub()
    if reason == "draft":
        client.draft = True
    elif reason == "immutable":
        client.immutable = True
    elif reason == "wrong-tag":
        client.tag_sha = "b" * 40
    else:
        client.assets["a.whl"] = (1, assets[0].read_bytes())
    with pytest.raises(ValueError):
        _attach(client, assets)
    assert client.uploads == []


def test_read_only_plan_does_not_upload(assets: list[Path]) -> None:
    client = FakeGitHub()
    assert _attach(client, assets, execute=False)["missing"] == ["a.whl", "b.json"]
    assert client.uploads == []


def test_corrupt_download_cannot_be_preserved(assets: list[Path]) -> None:
    client = FakeGitHub()
    client.assets["a.whl"] = (2, assets[0].read_bytes())

    def corrupt(repo: str, asset_id: int, destination: Path) -> None:
        destination.write_bytes(b"corrupt")

    client.download_asset = corrupt  # type: ignore[method-assign]
    with pytest.raises(ValueError, match="bytes"):
        _attach(client, assets)
    assert client.uploads == []


def test_symlink_and_duplicate_input_names_are_rejected(assets: list[Path]) -> None:
    client = FakeGitHub()
    link = assets[0].parent / "linked.whl"
    try:
        link.symlink_to(assets[0])
    except OSError:
        pytest.skip("symlinks unavailable")
    for paths in ([link], [assets[0], assets[0]]):
        with pytest.raises(ValueError):
            _attach(client, paths)
    assert not client.uploads


def test_immutable_complete_release_is_verified_without_writes(assets: list[Path]) -> None:
    client = FakeGitHub()
    client.immutable = True
    for index, path in enumerate(assets, 2):
        client.assets[path.name] = (index, path.read_bytes())
    assert _attach(client, assets)["uploaded"] == []
    assert not client.uploads


def test_concurrent_target_addition_stops_before_next_upload(assets: list[Path]) -> None:
    client = FakeGitHub()
    upload = client.upload_asset

    def race(repo: str, release_id: int, path: Path) -> None:
        upload(repo, release_id, path)
        client.assets["b.json"] = (99, assets[1].read_bytes())

    client.upload_asset = race  # type: ignore[method-assign]
    with pytest.raises(ValueError, match="changed during backfill"):
        _attach(client, assets)
    assert client.uploads == ["a.whl"]
    assert client.assets["b.json"][0] == 99


def test_readback_conflict_fails_without_replacing(assets: list[Path]) -> None:
    client = FakeGitHub()
    upload = client.upload_asset

    def corrupt(repo: str, release_id: int, path: Path) -> None:
        upload(repo, release_id, path)
        if path.name == "b.json":
            identity, _ = client.assets[path.name]
            client.assets[path.name] = (identity, b"different")

    client.upload_asset = corrupt  # type: ignore[method-assign]
    with pytest.raises(ValueError, match="digest|size"):
        _attach(client, assets)
    assert client.uploads == ["a.whl", "b.json"]


def test_legacy_workflow_attachments_use_pinned_helper_checkout() -> None:
    import yaml

    root = Path(__file__).resolve().parents[2]
    for filename in (
        "publish-python.yml",
        "publish-npm.yml",
        "publish-protocol-schemas.yml",
        "publish-mcpb.yml",
        "publish-kicad-pcm.yml",
    ):
        data = yaml.safe_load((root / ".github/workflows" / filename).read_text())
        jobs = data["jobs"]
        steps = jobs["build" if filename == "publish-python.yml" else "publish"]["steps"]
        load = next(s for s in steps if s.get("name") == "Load reviewed release attachment helper")
        assert load["with"]["ref"] == "$" + "{{ github.workflow_sha }}"
        assert load["with"]["path"] == ".release-tools"
        assert load["with"]["persist-credentials"] is False
        attachments = [s for s in steps if s.get("name", "").startswith("Attach ")]
        assert len(attachments) == (2 if filename == "publish-npm.yml" else 1)
        for step in attachments:
            assert steps.index(load) < steps.index(step)
            assert "python3 -P -m scripts.attach_published_release_assets" in step["run"]
            assert "--execute" in step["run"]
            assert "--clobber" not in step["run"]

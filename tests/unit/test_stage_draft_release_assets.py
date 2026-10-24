"""No network or GitHub writes: adversarial draft staging lifecycle simulations."""

from __future__ import annotations

import copy
import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, BinaryIO, cast

import pytest

from scripts.check_draft_release_inventory import digest, manifest_for
from scripts.stage_draft_release_assets import GitHubCLI, stage

REPO = "oaslananka/kicad-mcp-pro"
TAG = "mcp-server-v4.4.0"
SHA = "a" * 40


class FakeGitHub:
    def __init__(self, file_bytes: dict[str, bytes], *, existing: tuple[str, ...] = ()) -> None:
        self.files = file_bytes.copy()
        self.remote = {name: file_bytes[name] for name in existing}
        self.commit_sha = SHA
        self.id = 42
        self.published = False
        self.upload_calls: list[str] = []
        self.download_calls: list[int] = []
        self.tag_calls = 0
        self.release_calls = 0
        self.corrupt_download: str | None = None
        self.extra_asset: str | None = None
        self.bad_id = False
        self.stop_upload = False
        self.publish_on: int | None = None

    def release(self, repo: str, release_id: int) -> dict[str, Any]:
        assert repo == REPO
        assert release_id == self.id
        self.release_calls += 1
        if self.publish_on == self.release_calls:
            self.published = True
        assets = [
            {
                "id": 100 + index,
                "name": name,
                "size": len(payload),
                "state": "uploaded",
                "digest": "sha256:" + hashlib.sha256(payload).hexdigest(),
            }
            for index, (name, payload) in enumerate(sorted(self.remote.items()))
        ]
        if self.bad_id and assets:
            assets[0]["id"] = -1
        if self.extra_asset:
            assets.append({"id": 999, "name": self.extra_asset, "size": 3, "state": "uploaded"})
        return {
            "id": self.id,
            "url": f"https://api.github.com/repos/{repo}/releases/{self.id}",
            "tag_name": TAG,
            "draft": not self.published,
            "published_at": "2026-10-24T00:00:00Z" if self.published else None,
            "assets": assets,
        }

    def tag_commit(self, repo: str, tag: str) -> str:
        assert repo == REPO
        assert tag == TAG
        self.tag_calls += 1
        return self.commit_sha

    def download_asset(self, repo: str, asset_id: int, destination: Path) -> None:
        assert repo == REPO
        self.download_calls.append(asset_id)
        name = sorted(self.remote)[asset_id - 100]
        payload = self.remote[name]
        if name == self.corrupt_download:
            payload = b"malformed bytes"
        destination.write_bytes(payload)

    def upload_asset(self, repo: str, release_id: int, path: Path) -> None:
        assert repo == REPO
        assert release_id == self.id
        self.upload_calls.append(path.name)
        if self.stop_upload:
            raise ValueError("simulated GitHub transport rejection")
        if path.name in self.remote:
            raise ValueError("overwrite would be required")
        self.remote[path.name] = path.read_bytes()


def _case(tmp_path: Path, *, existing: tuple[str, ...] = ()) -> tuple[FakeGitHub, dict[str, Any]]:
    files = {"A.whl": b"validated wheel", "B.tar.gz": b"validated source"}
    approved = tmp_path / "approved"
    approved.mkdir()
    for name, payload in files.items():
        (approved / name).write_bytes(payload)
    pinned = tmp_path / "pinned.json"
    pinned.write_text(json.dumps(manifest_for(approved, TAG, SHA)))
    fake = FakeGitHub(files, existing=existing)
    kwargs = {
        "repo": REPO,
        "release_id": 42,
        "tag": TAG,
        "source_commit": SHA,
        "approved_dir": approved,
        "manifest_path": pinned,
        "manifest_sha256": digest(pinned),
    }
    return fake, kwargs


@pytest.mark.parametrize("existing", [(), ("A.whl",), ("A.whl", "B.tar.gz")])
def test_plan_is_read_only(tmp_path: Path, existing: tuple[str, ...]) -> None:
    client, args = _case(tmp_path, existing=existing)
    before = copy.deepcopy(client.remote)
    result = stage(client, **args)
    assert result["mode"] == "read-only"
    assert result["releaseId"] == 42
    assert result["preserveExisting"] == list(existing)
    assert result["uploadMissingOnly"] == sorted(set(client.files) - set(existing))
    assert client.remote == before
    assert client.upload_calls == []
    assert client.release_calls == 1


@pytest.mark.parametrize("existing", [(), ("A.whl",), ("A.whl", "B.tar.gz")])
def test_execute_only_missing_and_verify_fresh_draft(
    tmp_path: Path, existing: tuple[str, ...]
) -> None:
    client, args = _case(tmp_path, existing=existing)
    result = stage(client, **args, execute_uploads=True)
    assert result["mode"] == "uploaded-and-verified"
    assert result["preserveExisting"] == sorted(client.files)
    assert result["uploadMissingOnly"] == []
    assert result["readyForFinalInventoryCheck"]
    assert client.upload_calls == sorted(set(client.files) - set(existing))
    assert client.remote == client.files
    assert client.release_calls == 3
    assert not client.published


@pytest.mark.parametrize("published_on", [1, 2, 3])
def test_publication_at_any_check_aborts(tmp_path: Path, published_on: int) -> None:
    client, args = _case(tmp_path, existing=("A.whl",))
    client.publish_on = published_on
    with pytest.raises(ValueError, match="draft|published"):
        stage(client, **args, execute_uploads=True)
    if published_on <= 2:
        assert client.upload_calls == []


def test_never_replaces_corrupted_existing_asset(tmp_path: Path) -> None:
    client, args = _case(tmp_path, existing=("A.whl",))
    client.remote["A.whl"] = b"tampered"
    with pytest.raises(ValueError, match="digest|size|bytes"):
        stage(client, **args, execute_uploads=True)
    assert client.upload_calls == []


def test_independently_downloaded_bytes_are_verified(tmp_path: Path) -> None:
    client, args = _case(tmp_path, existing=("A.whl",))
    client.corrupt_download = "A.whl"
    with pytest.raises(ValueError, match="bytes mismatch"):
        stage(client, **args, execute_uploads=True)
    assert not client.upload_calls


def test_bad_asset_id_fails_before_download(tmp_path: Path) -> None:
    client, args = _case(tmp_path, existing=("A.whl",))
    client.bad_id = True
    with pytest.raises(ValueError, match="asset ID"):
        stage(client, **args)
    assert client.download_calls == []


def test_unaccounted_asset_aborts(tmp_path: Path) -> None:
    client, args = _case(tmp_path, existing=("A.whl",))
    client.extra_asset = "unreviewed-asset.zip"
    with pytest.raises(ValueError, match="unknown or duplicate"):
        stage(client, **args, execute_uploads=True)
    assert not client.upload_calls


def test_wrong_commit_aborts(tmp_path: Path) -> None:
    client, args = _case(tmp_path)
    client.commit_sha = "b" * 40
    with pytest.raises(ValueError, match="tag commit"):
        stage(client, **args, execute_uploads=True)
    assert not client.upload_calls


def test_partial_upload_failure_leaves_recoverable_draft(tmp_path: Path) -> None:
    client, args = _case(tmp_path)
    client.stop_upload = True
    with pytest.raises(ValueError, match="transport"):
        stage(client, **args, execute_uploads=True)
    assert not client.published
    assert not client.remote
    client.stop_upload = False
    assert stage(client, **args, execute_uploads=True)["readyForFinalInventoryCheck"]


def test_changed_local_artifact_rejected_before_upload(tmp_path: Path) -> None:
    client, args = _case(tmp_path)
    (args["approved_dir"] / "A.whl").write_bytes(b"new source")
    with pytest.raises(ValueError, match="pinned manifest"):
        stage(client, **args, execute_uploads=True)
    assert not client.upload_calls


def test_changed_manifest_pin_rejected_before_api(tmp_path: Path) -> None:
    client, args = _case(tmp_path)
    args["manifest_sha256"] = "f" * 64
    with pytest.raises(ValueError, match="digest"):
        stage(client, **args, execute_uploads=True)
    assert client.release_calls == 0


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("repo", "unqualified"),
        ("repo", "owner/foo/extra"),
        ("release_id", 0),
        ("release_id", True),
        ("release_id", -1),
        ("source_commit", "abc"),
        ("tag", "name/other"),
        ("tag", "-malformed"),
    ],
)
def test_invalid_arguments_never_access_github(
    tmp_path: Path, field: str, replacement: object
) -> None:
    client, args = _case(tmp_path)
    args[field] = replacement
    with pytest.raises(ValueError):
        stage(client, **args, execute_uploads=True)
    assert client.release_calls == 0


def test_cli_requires_exact_write_confirmation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from scripts import stage_draft_release_assets as module

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "stage_draft_release_assets",
            "--repo",
            REPO,
            "--release-id",
            "42",
            "--tag",
            TAG,
            "--source-commit",
            SHA,
            "--approved-assets",
            str(tmp_path / "approved"),
            "--manifest",
            str(tmp_path / "approved.json"),
            "--manifest-sha256",
            "a" * 64,
            "--execute-uploads",
        ],
    )

    def must_not_stage(*args: object, **kwargs: object) -> dict[str, object]:
        raise AssertionError("stage must not run without matching confirmations")

    monkeypatch.setattr(module, "stage", must_not_stage)
    with pytest.raises(SystemExit) as error:
        module.main()
    assert error.value.code == 2


def test_cli_matching_confirmations_allow_upload_mode(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from scripts import stage_draft_release_assets as module

    approved = tmp_path / "approved"
    pinned = tmp_path / "pinned.json"
    calls: list[dict[str, object]] = []

    def fake_stage(client: object, **kwargs: object) -> dict[str, object]:
        calls.append(kwargs)
        return {"readyForFinalInventoryCheck": True}

    monkeypatch.setattr(module, "stage", fake_stage)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "stage_draft_release_assets",
            "--repo",
            REPO,
            "--release-id",
            "42",
            "--tag",
            TAG,
            "--source-commit",
            SHA,
            "--approved-assets",
            str(approved),
            "--manifest",
            str(pinned),
            "--manifest-sha256",
            "a" * 64,
            "--execute-uploads",
            "--confirm-repository",
            REPO,
            "--confirm-release-id",
            "42",
        ],
    )
    assert module.main() == 0
    assert calls == [
        {
            "repo": REPO,
            "release_id": 42,
            "tag": TAG,
            "source_commit": SHA,
            "approved_dir": approved,
            "manifest_path": pinned,
            "manifest_sha256": "a" * 64,
            "execute_uploads": True,
        }
    ]
    assert json.loads(capsys.readouterr().out)["readyForFinalInventoryCheck"]


def test_github_cli_upload_never_clobbers(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    commands: list[list[str]] = []

    def fake_run(args: list[str], **kwargs: object) -> SimpleNamespace:
        commands.append(args)
        payload = b'{"id":101,"name":"A.whl","state":"uploaded"}'
        return SimpleNamespace(args=args, returncode=0, stdout=payload, stderr=b"")

    monkeypatch.setattr("scripts.stage_draft_release_assets.subprocess.run", fake_run)
    monkeypatch.setattr("scripts.stage_draft_release_assets.shutil.which", lambda _: "/usr/bin/gh")
    client = GitHubCLI()
    client.upload_asset(REPO, 42, tmp_path / "A.whl")
    assert len(commands) == 1
    assert commands[0][:3] == [str(Path("/usr/bin/gh").resolve()), "api", "-X"]
    assert commands[0][-1] == (
        f"https://uploads.github.com/repos/{REPO}/releases/42/assets?name=A.whl"
    )
    assert "--clobber" not in commands[0]
    assert "--input" in commands[0]


@pytest.mark.parametrize("kind", ["commit", "tag", "blob", "malformed"])
def test_tag_dereference(monkeypatch: pytest.MonkeyPatch, kind: str) -> None:
    client = GitHubCLI()

    def api(route: str) -> dict[str, Any]:
        if "/git/ref/tags/" in route:
            return {"object": {"type": kind, "sha": SHA}}
        if "/git/tags/" in route:
            return {"object": {"type": "commit", "sha": SHA}}
        raise AssertionError(route)

    monkeypatch.setattr(client, "_json", api)
    if kind in {"commit", "tag"}:
        assert client.tag_commit(REPO, TAG) == SHA
    else:
        with pytest.raises(ValueError, match="tag|commit"):
            client.tag_commit(REPO, TAG)


def test_cli_json_parsing_and_api_route(monkeypatch: pytest.MonkeyPatch) -> None:
    from scripts import stage_draft_release_assets as module

    commands: list[list[str]] = []

    def fake_run(arguments: list[str]) -> bytes:
        commands.append(arguments)
        return b'{"id":42}'

    monkeypatch.setattr(module.GitHubCLI, "_run", staticmethod(fake_run))
    assert GitHubCLI().release(REPO, 42) == {"id": 42}
    assert commands == [["api", f"repos/{REPO}/releases/42"]]


@pytest.mark.parametrize("content", [b"null", b"[]", b"false", b"12"])
def test_non_object_api_response_fails(monkeypatch: pytest.MonkeyPatch, content: bytes) -> None:
    from scripts import stage_draft_release_assets as module

    monkeypatch.setattr(module.GitHubCLI, "_run", staticmethod(lambda _: content))
    client = GitHubCLI()
    with pytest.raises(ValueError, match="JSON object"):
        client.release(REPO, 42)


def test_cli_failed_exit_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:

    def broken(args: list[str], **kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(args=args, returncode=1, stdout=b"", stderr=b"failed")

    monkeypatch.setattr("scripts.stage_draft_release_assets.subprocess.run", broken)
    monkeypatch.setattr("scripts.stage_draft_release_assets.shutil.which", lambda _: "/usr/bin/gh")
    client = GitHubCLI()
    with pytest.raises(ValueError, match="exit 1"):
        client.release(REPO, 42)


def test_missing_github_cli_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:

    monkeypatch.setattr("scripts.stage_draft_release_assets.shutil.which", lambda _: None)
    client = GitHubCLI()
    with pytest.raises(ValueError, match="not installed"):
        client.release(REPO, 42)


def test_asset_download_streams_to_new_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:

    commands: list[list[str]] = []

    def fake_run(args: list[str], **kwargs: object) -> SimpleNamespace:
        commands.append(args)
        output = cast(BinaryIO, kwargs["stdout"])
        output.write(b"approved bytes")
        return SimpleNamespace(args=args, returncode=0, stdout=b"", stderr=b"")

    monkeypatch.setattr("scripts.stage_draft_release_assets.subprocess.run", fake_run)
    monkeypatch.setattr("scripts.stage_draft_release_assets.shutil.which", lambda _: "/usr/bin/gh")
    target = tmp_path / "download.bin"
    GitHubCLI().download_asset(REPO, 101, target)
    assert target.read_bytes() == b"approved bytes"
    assert commands[0][-1] == f"repos/{REPO}/releases/assets/101"
    assert "--clobber" not in commands[0]
    existing_client = GitHubCLI()
    with pytest.raises(FileExistsError):
        existing_client.download_asset(REPO, 101, target)


def test_download_error_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:

    def fake_run(args: list[str], **kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(args=args, returncode=2, stdout=b"", stderr=b"")

    monkeypatch.setattr("scripts.stage_draft_release_assets.subprocess.run", fake_run)
    monkeypatch.setattr("scripts.stage_draft_release_assets.shutil.which", lambda _: "/usr/bin/gh")
    missing_path = tmp_path / "missing.bin"
    client = GitHubCLI()
    with pytest.raises(ValueError, match="download failed"):
        client.download_asset(REPO, 101, missing_path)


def test_broken_tag_ref_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    from scripts import stage_draft_release_assets as module

    monkeypatch.setattr(module.GitHubCLI, "_json", lambda _, route: {"object": None})
    client = GitHubCLI()
    with pytest.raises(ValueError, match="invalid protected tag reference"):
        client.tag_commit(REPO, TAG)


def test_recursive_tag_loop_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    from scripts import stage_draft_release_assets as module

    monkeypatch.setattr(
        module.GitHubCLI, "_json", lambda _, route: {"object": {"sha": SHA, "type": "tag"}}
    )
    client = GitHubCLI()
    with pytest.raises(ValueError, match="maximum depth"):
        client.tag_commit(REPO, TAG)


def test_upload_failure_is_not_retried_automatically(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, args = _case(tmp_path)
    client.stop_upload = True
    with pytest.raises(ValueError, match="transport"):
        stage(client, **args, execute_uploads=True)
    assert client.upload_calls == ["A.whl"]


@pytest.mark.parametrize(
    "response",
    [
        b"null",
        b"[]",
        b'{"id":0,"name":"A.whl","state":"uploaded"}',
        b'{"id":true,"name":"A.whl","state":"uploaded"}',
        b'{"id":101,"name":"other.whl","state":"uploaded"}',
        b'{"id":101,"name":"A.whl","state":"starter"}',
    ],
)
def test_api_upload_requires_valid_ack(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, response: bytes
) -> None:
    from scripts import stage_draft_release_assets as module

    monkeypatch.setattr(module.GitHubCLI, "_run", staticmethod(lambda _: response))
    path = tmp_path / "A.whl"
    client = GitHubCLI()
    with pytest.raises(ValueError, match="did not confirm"):
        client.upload_asset(REPO, 42, path)


def test_api_asset_name_is_url_encoded(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from scripts import stage_draft_release_assets as module

    arguments: list[list[str]] = []

    def fake_run(args: list[str]) -> bytes:
        arguments.append(args)
        return b'{"id":10,"name":"my asset #1.whl","state":"uploaded"}'

    monkeypatch.setattr(module.GitHubCLI, "_run", staticmethod(fake_run))
    path = tmp_path / "my asset #1.whl"
    GitHubCLI().upload_asset(REPO, 42, path)
    assert arguments[0][-1].endswith("/releases/42/assets?name=my%20asset%20%231.whl")

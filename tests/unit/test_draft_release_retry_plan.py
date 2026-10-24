"""Fail-closed, read-only draft retry planning and partial-publish recovery."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from scripts.check_draft_release_inventory import digest, manifest_for
from scripts.plan_draft_release_retry import main, plan

TAG = "mcp-server-v4.4.0"
SHA = "a" * 40
REPO = "oaslananka/kicad-mcp-pro"


def _case(tmp_path: Path, *, existing: int = 1) -> dict[str, Any]:
    approved_dir = tmp_path / "approved"
    downloaded_existing_dir = tmp_path / "downloaded"
    approved_dir.mkdir()
    downloaded_existing_dir.mkdir()
    for name, content in [("a.whl", b"good-wheel"), ("b.tar.gz", b"good-source")]:
        (approved_dir / name).write_bytes(content)
    manifest = tmp_path / "approved.json"
    manifest.write_text(json.dumps(manifest_for(approved_dir, TAG, SHA)))
    entries = json.loads(manifest.read_text())["assets"]
    for a in entries[:existing]:
        (downloaded_existing_dir / a["name"]).write_bytes((approved_dir / a["name"]).read_bytes())
    release = {
        "tag_name": TAG,
        "draft": True,
        "published_at": None,
        "id": 42,
        "url": f"https://api.github.com/repos/{REPO}/releases/42",
        "assets": [
            {
                "name": a["name"],
                "size": a["size"],
                "digest": f"sha256:{a['sha256']}",
                "state": "uploaded",
            }
            for a in entries[:existing]
        ],
    }
    return {
        "approved_dir": approved_dir,
        "downloaded_existing_dir": downloaded_existing_dir,
        "manifest_path": manifest,
        "manifest_sha256": digest(manifest),
        "release": release,
        "repo": REPO,
        "tag": TAG,
        "source_commit": SHA,
        "tag_commit": SHA,
    }


@pytest.mark.parametrize("existing", [0, 1, 2])
def test_draft_retry_plans_missing_only(tmp_path: Path, existing: int) -> None:
    case = _case(tmp_path, existing=existing)
    result = plan(**case)
    assert result["releaseTag"] == TAG
    assert result["sourceCommit"] == SHA
    assert result["preserveExisting"] == ["a.whl", "b.tar.gz"][:existing]
    assert result["uploadMissingOnly"] == ["a.whl", "b.tar.gz"][existing:]
    assert result["readyForFinalInventoryCheck"] is (existing == 2)


def test_existing_digest_can_be_absent_if_downloaded_bytes_match(tmp_path: Path) -> None:
    case = _case(tmp_path)
    case["release"]["assets"][0].pop("digest")
    assert plan(**case)["uploadMissingOnly"] == ["b.tar.gz"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("draft", False),
        ("published_at", "2026-10-24T01:22:00Z"),
        ("tag_name", "old-tag"),
        ("url", "https://api.github.com/repos/other/repo/releases/42"),
        ("id", 0),
        ("id", True),
        ("id", "42"),
        ("id", 43),
        ("url", "https://api.github.com/repos/oaslananka/kicad-mcp-pro/releases/42?bad=1"),
    ],
)
def test_only_approved_draft_and_identity_accepted(
    tmp_path: Path, field: str, value: object
) -> None:
    case = _case(tmp_path)
    case["release"][field] = value
    with pytest.raises(ValueError):
        plan(**case)


def test_wrong_tag_commit_fails(tmp_path: Path) -> None:
    case = _case(tmp_path)
    case["tag_commit"] = "b" * 40
    with pytest.raises(ValueError, match="tag commit"):
        plan(**case)


@pytest.mark.parametrize("mutation", ["extra", "duplicate", "bad-size", "bad-hash", "processing"])
def test_bad_remote_inventory_fails_closed(tmp_path: Path, mutation: str) -> None:
    case = _case(tmp_path)
    assets = case["release"]["assets"]
    if mutation == "extra":
        assets.append({"name": "stranger.exe", "size": 10, "state": "uploaded"})
    elif mutation == "duplicate":
        assets.append(dict(assets[0]))
    elif mutation == "bad-size":
        assets[0]["size"] = 10000
    elif mutation == "bad-hash":
        assets[0]["digest"] = "sha256:" + "f" * 64
    else:
        assets[0]["state"] = "starter"
    with pytest.raises(ValueError):
        plan(**case)


def test_existing_asset_must_be_downloaded(tmp_path: Path) -> None:
    case = _case(tmp_path)
    (case["downloaded_existing_dir"] / "a.whl").unlink()
    with pytest.raises(ValueError, match="independently downloaded"):
        plan(**case)


def test_corrupted_download_is_not_overwritten(tmp_path: Path) -> None:
    case = _case(tmp_path)
    (case["downloaded_existing_dir"] / "a.whl").write_bytes(b"bad-bytes-!")
    with pytest.raises(ValueError, match="bytes mismatch"):
        plan(**case)


def test_extra_downloaded_asset_fails(tmp_path: Path) -> None:
    case = _case(tmp_path)
    (case["downloaded_existing_dir"] / "extra.dat").write_bytes(b"unexpected")
    with pytest.raises(ValueError, match="unexpected or unaccounted"):
        plan(**case)


def test_mutated_local_build_does_not_resume(tmp_path: Path) -> None:
    case = _case(tmp_path)
    (case["approved_dir"] / "a.whl").write_bytes(b"different rebuilt wheel")
    with pytest.raises(ValueError, match="approved local build outputs"):
        plan(**case)


def test_manifest_pin_prevents_mutation(tmp_path: Path) -> None:
    case = _case(tmp_path)
    case["manifest_sha256"] = "f" * 64
    with pytest.raises(ValueError, match="approved manifest digest"):
        plan(**case)


def test_manifest_symlink_rejected(tmp_path: Path) -> None:
    case = _case(tmp_path)
    link = tmp_path / "link.json"
    link.symlink_to(case["manifest_path"])
    case["manifest_path"] = link
    with pytest.raises(ValueError, match="approved manifest digest"):
        plan(**case)


def test_empty_downloads_are_valid_if_draft_has_no_assets(tmp_path: Path) -> None:
    case = _case(tmp_path, existing=0)
    assert plan(**case)["uploadMissingOnly"] == ["a.whl", "b.tar.gz"]


def test_empty_invalid_download_file_fails(tmp_path: Path) -> None:
    case = _case(tmp_path)
    (case["downloaded_existing_dir"] / "empty.bin").touch()
    with pytest.raises(ValueError, match="invalid downloaded"):
        plan(**case)


def test_missing_local_manifest_entry_fails(tmp_path: Path) -> None:
    case = _case(tmp_path)
    (case["approved_dir"] / "b.tar.gz").unlink()
    with pytest.raises(ValueError, match="approved local build"):
        plan(**case)


def test_cli_produces_read_only_retry_plan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    case = _case(tmp_path)
    release_path = tmp_path / "release.json"
    release_path.write_text(json.dumps(case["release"]))
    monkeypatch.setattr(
        "sys.argv",
        [
            "plan-draft-retry",
            "--approved-assets",
            str(case["approved_dir"]),
            "--downloaded-existing",
            str(case["downloaded_existing_dir"]),
            "--manifest",
            str(case["manifest_path"]),
            "--manifest-sha256",
            case["manifest_sha256"],
            "--release-json",
            str(release_path),
            "--repo",
            REPO,
            "--tag",
            TAG,
            "--source-commit",
            SHA,
            "--tag-commit",
            SHA,
        ],
    )
    assert main() == 0
    assert json.loads(capsys.readouterr().out)["uploadMissingOnly"] == ["b.tar.gz"]


@pytest.mark.parametrize("payload", [None, [], "malformed", 999, False])
def test_non_object_release_json_fails_closed(tmp_path: Path, payload: object) -> None:
    case = _case(tmp_path)
    case["release"] = payload
    with pytest.raises(ValueError, match="must be a JSON object"):
        plan(**case)


def test_unapproved_manifest_path_rejected(tmp_path: Path) -> None:
    case = _case(tmp_path)
    case["manifest_path"] = Path.home().parent / "unapproved-release-fixture.txt"
    with pytest.raises(ValueError, match="outside approved automation roots"):
        plan(**case)


def test_unapproved_download_directory_rejected(tmp_path: Path) -> None:
    case = _case(tmp_path)
    case["downloaded_existing_dir"] = Path.home().parent / "unapproved-release-fixture"
    with pytest.raises(ValueError, match="outside approved automation roots"):
        plan(**case)


def test_manifest_hash_and_json_use_same_byte_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = _case(tmp_path)
    manifest = case["manifest_path"]
    original_read_bytes = Path.read_bytes
    original_read_text = Path.read_text
    reads = []

    def counted_read(path: Path) -> bytes:
        if path == manifest:
            reads.append(path)
        return original_read_bytes(path)

    def reject_reread(path: Path, *args: object, **kwargs: object) -> str:
        if path == manifest:
            raise AssertionError("trusted manifest must not be reopened")
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_bytes", counted_read)
    monkeypatch.setattr(Path, "read_text", reject_reread)
    plan(**case)
    assert reads == [manifest]

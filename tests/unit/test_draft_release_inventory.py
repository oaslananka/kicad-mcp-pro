"""Draft-only asset acceptance tests; never creates or publishes GitHub Releases."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from scripts.check_draft_release_inventory import digest, main, manifest_for, verify

REPO = "oaslananka/kicad-mcp-pro"
TAG = "mcp-server-v4.4.0"
SOURCE = "a" * 40


def _case(tmp_path: Path) -> dict[str, Any]:
    directory = tmp_path / "downloads"
    directory.mkdir()
    (directory / "kicad-package.whl").write_bytes(b"verified-wheel")
    (directory / "SBOM.cdx.json").write_bytes(b"verified-sbom")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps(manifest_for(directory, TAG, SOURCE)))
    data = json.loads(manifest.read_text())
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
                "state": "uploaded",
                "digest": f"sha256:{a['sha256']}",
            }
            for a in data["assets"]
        ],
    }
    return {
        "directory": directory,
        "manifest_path": manifest,
        "manifest_sha256": digest(manifest),
        "release": release,
        "repository": REPO,
        "tag": TAG,
        "source_commit": SOURCE,
        "tag_commit": SOURCE,
    }


def test_complete_draft_inventory_is_accepted(tmp_path: Path) -> None:
    verify(**_case(tmp_path))


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("draft", False, "published"),
        ("published_at", "2026-10-24T01:00:00Z", "publication timestamp"),
        ("tag_name", "mcp-server-v4.3.0", "incorrect tag"),
        (
            "url",
            "https://api.github.com/repos/attacker/kicad-mcp-pro/releases/42",
            "repository",
        ),
        ("id", 0, "repository"),
        ("id", True, "repository"),
        ("id", "42", "repository"),
        ("id", 43, "repository"),
        (
            "url",
            "https://api.github.com/repos/oaslananka/kicad-mcp-pro/releases/tag/mcp-server-v4.4.0",
            "repository",
        ),
        (
            "url",
            "https://api.github.com/repos/oaslananka/kicad-mcp-pro/releases/42?other=true",
            "repository",
        ),
    ],
)
def test_release_identity_and_draft_enforced(
    tmp_path: Path, field: str, value: object, message: str
) -> None:
    case = _case(tmp_path)
    case["release"][field] = value
    with pytest.raises(ValueError, match=message):
        verify(**case)


def test_protected_tag_must_match_exact_commit(tmp_path: Path) -> None:
    case = _case(tmp_path)
    case["tag_commit"] = "b" * 40
    with pytest.raises(ValueError, match="protected release tag"):
        verify(**case)


@pytest.mark.parametrize("mutation", ["remove", "unexpected", "duplicate"])
def test_asset_inventory_must_match_exactly(tmp_path: Path, mutation: str) -> None:
    case = _case(tmp_path)
    assets = case["release"]["assets"]
    if mutation == "remove":
        assets.pop()
    elif mutation == "unexpected":
        assets.append({"name": "another.zip", "size": 1})
    else:
        assets.append(dict(assets[0]))
    with pytest.raises(ValueError, match="duplicate asset|assets differ"):
        verify(**case)


def test_modified_downloaded_bytes_rejected(tmp_path: Path) -> None:
    case = _case(tmp_path)
    (case["directory"] / "kicad-package.whl").write_bytes(b"modified-wheel")
    with pytest.raises(ValueError, match="downloaded draft asset"):
        verify(**case)


def test_manifest_must_have_independent_sha256_pin(tmp_path: Path) -> None:
    case = _case(tmp_path)
    case["manifest_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="trusted manifest"):
        verify(**case)


def test_manifest_source_commit_mismatch_rejected(tmp_path: Path) -> None:
    case = _case(tmp_path)
    case["source_commit"] = "b" * 40
    case["tag_commit"] = "b" * 40
    with pytest.raises(ValueError, match="manifest source"):
        verify(**case)


@pytest.mark.parametrize("key", ["size", "digest", "state"])
def test_remote_asset_metadata_checked(tmp_path: Path, key: str) -> None:
    case = _case(tmp_path)
    entry = case["release"]["assets"][0]
    entry[key] = {"size": 999, "digest": "sha256:" + "f" * 64, "state": "starter"}[key]
    with pytest.raises(ValueError, match="mismatch"):
        verify(**case)


def test_symlink_asset_rejected(tmp_path: Path) -> None:
    case = _case(tmp_path)
    (case["directory"] / "malicious.whl").symlink_to(tmp_path / "outside.whl")
    with pytest.raises(ValueError, match="linked release asset"):
        verify(**case)


def test_directory_traversal_in_manifest_rejected(tmp_path: Path) -> None:
    case = _case(tmp_path)
    manifest = json.loads(case["manifest_path"].read_text())
    manifest["assets"][0]["name"] = "../escape"
    case["manifest_path"].write_text(json.dumps(manifest))
    case["manifest_sha256"] = digest(case["manifest_path"])
    with pytest.raises(ValueError, match="invalid or duplicate asset name"):
        verify(**case)


def test_empty_asset_directory_rejected(tmp_path: Path) -> None:
    directory = tmp_path / "empty"
    directory.mkdir()
    with pytest.raises(ValueError, match="empty"):
        manifest_for(directory, TAG, SOURCE)


def test_repository_rejects_forged_identity(tmp_path: Path) -> None:
    case = _case(tmp_path)
    case["repository"] = "attacker/repo"
    with pytest.raises(ValueError, match="expected repository"):
        verify(**case)


def test_cli_generate_and_verify(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    case = _case(tmp_path)
    manifest = tmp_path / "approved.json"
    release_json = tmp_path / "github-release.json"
    release_json.write_text(json.dumps(case["release"]))
    monkeypatch.setattr(
        "sys.argv",
        [
            "verify-inventory",
            "manifest",
            "--assets-dir",
            str(case["directory"]),
            "--tag",
            TAG,
            "--source-commit",
            SOURCE,
            "--output",
            str(manifest),
        ],
    )
    assert main() == 0
    monkeypatch.setattr(
        "sys.argv",
        [
            "verify-inventory",
            "verify",
            "--assets-dir",
            str(case["directory"]),
            "--tag",
            TAG,
            "--source-commit",
            SOURCE,
            "--tag-commit",
            SOURCE,
            "--manifest",
            str(manifest),
            "--manifest-sha256",
            digest(manifest),
            "--release-json",
            str(release_json),
            "--repo",
            REPO,
        ],
    )
    assert main() == 0


def test_manifest_symlink_rejected(tmp_path: Path) -> None:
    case = _case(tmp_path)
    path = tmp_path / "link.json"
    path.symlink_to(case["manifest_path"])
    case["manifest_path"] = path
    with pytest.raises(ValueError, match="manifest may not be a symlink"):
        verify(**case)


def test_unexpected_file_in_download_directory_rejected(tmp_path: Path) -> None:
    case = _case(tmp_path)
    (case["directory"] / "unexpected.txt").write_bytes(b"surprise")
    with pytest.raises(ValueError, match="assets differ"):
        verify(**case)


def test_missing_github_digest_is_supported_when_local_matches(tmp_path: Path) -> None:
    case = _case(tmp_path)
    case["release"]["assets"][0].pop("digest")
    verify(**case)


def test_invalid_manifest_schema_rejected(tmp_path: Path) -> None:
    case = _case(tmp_path)
    manifest = json.loads(case["manifest_path"].read_text())
    manifest["schemaVersion"] = 2000
    case["manifest_path"].write_text(json.dumps(manifest))
    case["manifest_sha256"] = digest(case["manifest_path"])
    with pytest.raises(ValueError, match="manifest schema"):
        verify(**case)


def test_invalid_release_asset_name_rejected(tmp_path: Path) -> None:
    case = _case(tmp_path)
    case["release"]["assets"][0]["name"] = "unsafe\nname.zip"
    with pytest.raises(ValueError, match="invalid or duplicate asset name"):
        verify(**case)


def test_invalid_commit_sha_rejected_when_generating(tmp_path: Path) -> None:
    case = _case(tmp_path)
    with pytest.raises(ValueError, match="source commit"):
        manifest_for(case["directory"], TAG, "not-a-commit")


def test_invalid_tag_rejected_when_generating(tmp_path: Path) -> None:
    case = _case(tmp_path)
    with pytest.raises(ValueError, match="invalid release tag"):
        manifest_for(case["directory"], "../unsafe", SOURCE)


def test_invalid_repository_rejected(tmp_path: Path) -> None:
    case = _case(tmp_path)
    case["repository"] = "too-many/components/repo"
    with pytest.raises(ValueError, match="invalid repository"):
        verify(**case)


@pytest.mark.parametrize("payload", [None, [], "invalid", 42, False])
def test_release_metadata_must_be_json_object(tmp_path: Path, payload: object) -> None:
    case = _case(tmp_path)
    case["release"] = payload
    with pytest.raises(ValueError, match="release metadata must be a JSON object"):
        verify(**case)


def test_unapproved_absolute_path_is_rejected() -> None:
    from scripts.check_draft_release_inventory import digest

    outside_path = Path.home().parent / "unapproved-release-fixture.txt"
    with pytest.raises(ValueError, match="outside approved automation roots"):
        digest(outside_path)


def test_unapproved_asset_directory_is_rejected() -> None:
    outside_directory = Path.home().parent / "unapproved-release-fixture"
    with pytest.raises(ValueError, match="outside approved automation roots"):
        manifest_for(outside_directory, TAG, SOURCE)


def test_trusted_manifest_is_hashed_and_parsed_from_single_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = _case(tmp_path)
    original = Path.read_bytes
    manifest = case["manifest_path"]
    reads = []

    def read_once(path: Path) -> bytes:
        if path == manifest:
            reads.append(path)
        return original(path)

    original_text = Path.read_text

    def reject_reread(path: Path, *args: object, **kwargs: object) -> str:
        if path == manifest:
            raise AssertionError("manifest was reopened after digest comparison")
        return original_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_bytes", read_once)
    monkeypatch.setattr(Path, "read_text", reject_reread)
    verify(**case)
    assert reads == [manifest]

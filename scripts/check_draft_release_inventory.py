"""Fail-closed, read-only draft Release inventory gate for #1179.

The manifest is generated from approved build outputs, then its SHA-256 is
passed independently to this verifier. The caller must fetch release JSON and
assets from GitHub and resolve the protected tag to its exact commit.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from scripts.runtime_path_safety import approved_runtime_path

_SHA = re.compile(r"^[0-9a-f]{64}$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


def digest(path: Path) -> str:
    path = approved_runtime_path(path)
    sha = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            sha.update(chunk)
    return sha.hexdigest()


def _files(directory: Path) -> dict[str, Path]:
    if directory.is_symlink():
        raise ValueError("artifact directory may not be a symlink")
    directory = approved_runtime_path(directory)
    if not directory.is_dir():
        raise ValueError("artifact directory must be a real directory")
    paths = list(directory.iterdir())
    if not paths:
        raise ValueError("artifact directory is empty")
    files = {}
    for path in paths:
        if (
            path.is_symlink()
            or not path.is_file()
            or path.name in {".", ".."}
            or any(char in path.name for char in "\r\n")
            or path.stat().st_size == 0
        ):
            raise ValueError(f"unsupported, empty or linked release asset: {path.name}")
        files[path.name] = path
    return files


def manifest_for(directory: Path, tag: str, source_commit: str) -> dict[str, Any]:
    if not _COMMIT.fullmatch(source_commit):
        raise ValueError("source commit must be an exact SHA-1")
    if not tag or "/" in tag or "\\" in tag or tag.startswith("-"):
        raise ValueError("invalid release tag")
    return {
        "schemaVersion": 1,
        "releaseTag": tag,
        "sourceCommit": source_commit,
        "assets": [
            {"name": name, "size": path.stat().st_size, "sha256": digest(path)}
            for name, path in sorted(_files(directory).items())
        ],
    }


def _valid_asset_name(name: object, seen: dict[str, dict[str, Any]]) -> bool:
    return (
        isinstance(name, str)
        and bool(name)
        and Path(name).name == name
        and "/" not in name
        and "\\" not in name
        and not any(char in name for char in "\r\n")
        and name not in seen
    )


def _asset_inventory(assets: object) -> dict[str, dict[str, Any]]:
    if not isinstance(assets, list) or not assets:
        raise ValueError("release asset inventory is missing or empty")
    result: dict[str, dict[str, Any]] = {}
    for asset in assets:
        if not isinstance(asset, dict):
            raise ValueError("invalid asset metadata")
        name = asset.get("name")
        if not isinstance(name, str) or not _valid_asset_name(name, result):
            raise ValueError(f"invalid or duplicate asset name: {name}")
        result[name] = asset
    return result


def _trusted_manifest(path: Path, expected_sha: str) -> dict[str, Any]:
    if path.is_symlink():
        raise ValueError("trusted manifest may not be a symlink")
    path = approved_runtime_path(path)
    payload = path.read_bytes()
    if not _SHA.fullmatch(expected_sha) or hashlib.sha256(payload).hexdigest() != expected_sha:
        raise ValueError("trusted manifest SHA-256 mismatch")
    manifest = json.loads(payload)
    if not isinstance(manifest, dict) or manifest.get("schemaVersion") != 1:
        raise ValueError("unsupported inventory manifest schema")
    return manifest


def _draft_release(
    release: object, repository: str, tag: str, source_commit: str, tag_commit: str
) -> dict[str, Any]:
    if not _REPOSITORY.fullmatch(repository):
        raise ValueError("invalid repository identity")
    if not _COMMIT.fullmatch(tag_commit) or tag_commit != source_commit:
        raise ValueError("protected release tag does not resolve to expected source")
    if not isinstance(release, dict):
        raise ValueError("release metadata must be a JSON object")
    if release.get("tag_name") != tag or release.get("draft") is not True:
        raise ValueError("release is missing, published or has incorrect tag")
    if release.get("published_at") is not None:
        raise ValueError("draft release has a publication timestamp")
    release_id = release.get("id")
    if (
        type(release_id) is not int
        or release_id <= 0
        or release.get("url") != f"https://api.github.com/repos/{repository}/releases/{release_id}"
    ):
        raise ValueError("release does not belong to the expected repository")
    return release


def _verify_asset(name: str, item: dict[str, Any], remote: dict[str, Any], path: Path) -> None:
    size, sha = item.get("size"), item.get("sha256")
    if type(size) is not int or size <= 0 or not isinstance(sha, str) or not _SHA.fullmatch(sha):
        raise ValueError(f"invalid trusted asset metadata: {name}")
    if path.stat().st_size != size or digest(path) != sha:
        raise ValueError(f"downloaded draft asset does not match manifest: {name}")
    if remote.get("size") != size or remote.get("state", "uploaded") != "uploaded":
        raise ValueError(f"draft asset size or upload state mismatch: {name}")
    if remote.get("digest") not in (None, f"sha256:{sha}"):
        raise ValueError(f"GitHub draft asset digest mismatch: {name}")


def _verify_inventory(directory: Path, manifest: dict[str, Any], release: dict[str, Any]) -> None:
    expected = _asset_inventory(manifest.get("assets"))
    actual = _asset_inventory(release.get("assets"))
    files = _files(directory)
    if set(expected) != set(actual) or set(expected) != set(files):
        raise ValueError("draft release assets differ from trusted manifest")
    for name, item in expected.items():
        _verify_asset(name, item, actual[name], files[name])


def verify(
    *,
    directory: Path,
    manifest_path: Path,
    manifest_sha256: str,
    release: object,
    repository: str,
    tag: str,
    source_commit: str,
    tag_commit: str,
) -> None:
    manifest = _trusted_manifest(manifest_path, manifest_sha256)
    draft = _draft_release(release, repository, tag, source_commit, tag_commit)
    if manifest.get("releaseTag") != tag or manifest.get("sourceCommit") != source_commit:
        raise ValueError("manifest source or release tag mismatch")
    _verify_inventory(directory, manifest, draft)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prepare = sub.add_parser("manifest", help="prepare inventory from reviewed build outputs")
    prepare.add_argument("--assets-dir", required=True, type=Path)
    prepare.add_argument("--tag", required=True)
    prepare.add_argument("--source-commit", required=True)
    prepare.add_argument("--output", required=True, type=Path)
    check = sub.add_parser("verify", help="check a GitHub draft before publication")
    check.add_argument("--assets-dir", required=True, type=Path)
    check.add_argument("--manifest", required=True, type=Path)
    check.add_argument("--manifest-sha256", required=True)
    check.add_argument("--release-json", required=True, type=Path)
    check.add_argument("--repo", required=True)
    check.add_argument("--tag", required=True)
    check.add_argument("--source-commit", required=True)
    check.add_argument("--tag-commit", required=True)
    args = parser.parse_args()
    try:
        if args.command == "manifest":
            payload = manifest_for(args.assets_dir, args.tag, args.source_commit)
            output = approved_runtime_path(args.output)
            output.write_text(
                json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8"
            )
            print(
                json.dumps(
                    {"manifest_sha256": digest(output), "asset_count": len(payload["assets"])}
                )
            )
        else:
            release_json = approved_runtime_path(args.release_json)
            release = json.loads(release_json.read_text(encoding="utf-8"))
            verify(
                directory=args.assets_dir,
                manifest_path=args.manifest,
                manifest_sha256=args.manifest_sha256,
                release=release,
                repository=args.repo,
                tag=args.tag,
                source_commit=args.source_commit,
                tag_commit=args.tag_commit,
            )
            print("draft Release inventory: PASS")
    except (OSError, ValueError) as exc:
        parser.exit(2, f"draft Release inventory: FAIL: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

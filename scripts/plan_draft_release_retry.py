"""Plan safe, idempotent retries of incomplete GitHub draft Releases (#1179).

Never uploads, deletes, edits, publishes, or overwrites assets. Every existing
draft asset must be independently downloaded and match the approved manifest.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from scripts.check_draft_release_inventory import digest, manifest_for
from scripts.runtime_path_safety import approved_runtime_path

_SCHEMA = 1


def _downloaded(directory: Path) -> dict[str, Path]:
    if directory.is_symlink():
        raise ValueError("downloaded draft inventory must be a real directory")
    directory = approved_runtime_path(directory)
    if not directory.is_dir():
        raise ValueError("downloaded draft inventory must be a real directory")
    result: dict[str, Path] = {}
    for file in directory.iterdir():
        if file.is_symlink() or not file.is_file() or not file.stat().st_size:
            raise ValueError(f"invalid downloaded draft asset: {file.name}")
        result[file.name] = file
    return result


def _approved_manifest(
    path: Path, expected_digest: str, approved_dir: Path, tag: str, source_commit: str
) -> dict[str, Any]:
    if path.is_symlink():
        raise ValueError("approved manifest digest mismatch")
    path = approved_runtime_path(path)
    payload = path.read_bytes()
    if hashlib.sha256(payload).hexdigest() != expected_digest:
        raise ValueError("approved manifest digest mismatch")
    manifest = json.loads(payload)
    if not isinstance(manifest, dict) or manifest.get("schemaVersion") != _SCHEMA:
        raise ValueError("unsupported manifest schema")
    if manifest != manifest_for(approved_dir, tag, source_commit):
        raise ValueError("approved local build outputs differ from pinned manifest")
    return manifest


def _draft_metadata(
    release: object, repo: str, tag: str, source_commit: str, tag_commit: str
) -> dict[str, Any]:
    if tag_commit != source_commit or len(tag_commit) != 40:
        raise ValueError("tag commit differs from reviewed source commit")
    if not isinstance(release, dict):
        raise ValueError("draft Release metadata must be a JSON object")
    if release.get("tag_name") != tag or release.get("draft") is not True:
        raise ValueError("only matching draft releases can be resumed")
    if release.get("published_at") is not None:
        raise ValueError("published release may not be resumed")
    release_id = release.get("id")
    if (
        type(release_id) is not int
        or release_id <= 0
        or release.get("url") != f"https://api.github.com/repos/{repo}/releases/{release_id}"
    ):
        raise ValueError("draft release repository identity mismatch")
    return release


def _verify_existing(
    asset: object,
    approved: dict[str, dict[str, Any]],
    observed: set[str],
    downloaded: dict[str, Path],
) -> None:
    if not isinstance(asset, dict):
        raise ValueError("invalid GitHub draft asset metadata")
    name = asset.get("name")
    if not isinstance(name, str) or name not in approved or name in observed:
        raise ValueError("unknown or duplicate asset in draft release")
    observed.add(name)
    expected = approved[name]
    if asset.get("state") != "uploaded" or asset.get("size") != expected["size"]:
        raise ValueError(f"draft asset is incomplete or has wrong size: {name}")
    if asset.get("digest") not in (None, f"sha256:{expected['sha256']}"):
        raise ValueError(f"draft asset GitHub digest mismatch: {name}")
    if name not in downloaded:
        raise ValueError(f"existing draft asset was not independently downloaded: {name}")
    if (
        downloaded[name].stat().st_size != expected["size"]
        or digest(downloaded[name]) != expected["sha256"]
    ):
        raise ValueError(f"existing draft asset bytes mismatch: {name}")


def _existing_names(
    approved: dict[str, dict[str, Any]], draft: dict[str, Any], downloaded_dir: Path
) -> set[str]:
    remote_assets = draft.get("assets")
    if not isinstance(remote_assets, list):
        raise ValueError("GitHub release asset inventory must be a list")
    downloaded = _downloaded(downloaded_dir)
    observed: set[str] = set()
    for asset in remote_assets:
        _verify_existing(asset, approved, observed, downloaded)
    if set(downloaded) != observed:
        raise ValueError("unexpected or unaccounted downloaded asset")
    return observed


def plan(
    *,
    approved_dir: Path,
    downloaded_existing_dir: Path,
    manifest_path: Path,
    manifest_sha256: str,
    release: object,
    repo: str,
    tag: str,
    source_commit: str,
    tag_commit: str,
) -> dict[str, object]:
    manifest = _approved_manifest(manifest_path, manifest_sha256, approved_dir, tag, source_commit)
    draft = _draft_metadata(release, repo, tag, source_commit, tag_commit)
    approved = {asset["name"]: asset for asset in manifest["assets"]}
    observed = _existing_names(approved, draft, downloaded_existing_dir)
    missing = sorted(set(approved) - observed)
    return {
        "releaseTag": tag,
        "sourceCommit": source_commit,
        "preserveExisting": sorted(observed),
        "uploadMissingOnly": missing,
        "readyForFinalInventoryCheck": not missing,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--approved-assets", required=True, type=Path)
    parser.add_argument("--downloaded-existing", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--release-json", required=True, type=Path)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--tag-commit", required=True)
    args = parser.parse_args()
    try:
        release_json = approved_runtime_path(args.release_json)
        release = json.loads(release_json.read_text(encoding="utf-8"))
        result = plan(
            approved_dir=args.approved_assets,
            downloaded_existing_dir=args.downloaded_existing,
            manifest_path=args.manifest,
            manifest_sha256=args.manifest_sha256,
            release=release,
            repo=args.repo,
            tag=args.tag,
            source_commit=args.source_commit,
            tag_commit=args.tag_commit,
        )
    except (OSError, ValueError) as exc:
        parser.exit(2, f"draft Release retry plan: FAIL: {exc}\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

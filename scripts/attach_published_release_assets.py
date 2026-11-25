"""Legacy published-release backfill: verify existing bytes, upload missing only.

This does not create, edit, publish, delete or replace a Release or asset.
It does not prove exclusive writer ownership and is not draft-first cutover.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
from collections.abc import Callable
from functools import partial
from os.path import basename
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Protocol

from scripts.check_draft_release_inventory import digest, manifest_for
from scripts.runtime_path_safety import approved_runtime_path
from scripts.stage_draft_release_assets import DraftClient, GitHubCLI

_REPOSITORIES = frozenset({"oaslananka/kicad-mcp-pro", "oaslananka-ops/kicad-mcp-pro"})
_TAG = re.compile(
    r"(?:mcp-server|mcp-npm|protocol-schemas)-v\d+\.\d+\.\d+(?:[+-][A-Za-z0-9.-]+)?", re.ASCII
)
_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,199}", re.ASCII)
_SHA = re.compile(r"[0-9a-f]{40}")


class PublishedClient(DraftClient, Protocol):
    def release_by_tag(self, repo: str, tag: str) -> dict[str, Any]: ...


class PublishedGitHubCLI(GitHubCLI):
    def release_by_tag(self, repo: str, tag: str) -> dict[str, Any]:
        return self._json(f"repos/{repo}/releases/tags/{tag}")


def _check_identity(release: dict[str, Any], repo: str, tag: str, release_id: int) -> None:
    if (
        type(release_id) is not int
        or release_id <= 0
        or release.get("id") != release_id
        or release.get("url") != f"https://api.github.com/repos/{repo}/releases/{release_id}"
        or release.get("tag_name") != tag
        or release.get("draft") is not False
        or not isinstance(release.get("published_at"), str)
        or not release["published_at"]
        or type(release.get("immutable")) is not bool
    ):
        raise ValueError("invalid published release identity or state")


def _snapshot_local(paths: list[Path], source_root: Path, destination: Path) -> None:
    # A separate reviewed workflow checkout may supply the helper for an
    # older source tag. Only its enclosing build checkout is an extra root.
    tool_root = Path(__file__).resolve().parents[1]
    extra_roots = (tool_root.parent,) if tool_root.name == ".release-tools" else ()
    root = approved_runtime_path(source_root, extra_roots=extra_roots)
    if not root.is_dir() or not paths:
        raise ValueError("missing approved source files")
    for path in paths:
        if path.is_symlink() or not _NAME.fullmatch(path.name):
            raise ValueError("invalid source asset name or link")
        source = path.resolve(strict=True)
        if not source.is_relative_to(root) or not source.is_file() or not source.stat().st_size:
            raise ValueError("source asset must be a nonempty file inside source root")
        target = destination / basename(path.name)
        if target.exists():
            raise ValueError("duplicate source asset name")
        with source.open("rb") as data, target.open("xb") as output:
            shutil.copyfileobj(data, output)


def _target_assets(
    release: dict[str, Any], approved: dict[str, dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    rows = release.get("assets")
    if not isinstance(rows, list):
        raise ValueError("invalid release asset inventory")
    names: set[str] = set()
    ids: set[int] = set()
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("invalid release asset entry")
        name, asset_id = row.get("name"), row.get("id")
        if (
            not isinstance(name, str)
            or name in names
            or type(asset_id) is not int
            or asset_id <= 0
            or asset_id in ids
        ):
            raise ValueError("invalid or duplicate release asset name or ID")
        names.add(name)
        ids.add(asset_id)
        if name not in approved:
            continue
        expected = approved[name]
        if (
            row.get("state") != "uploaded"
            or row.get("size") != expected["size"]
            or row.get("digest") not in (None, f"sha256:{expected['sha256']}")
        ):
            raise ValueError(f"existing asset size, state or digest differs: {name}")
        result[name] = row
    return result


def _verify_bytes(
    client: PublishedClient,
    repo: str,
    observed: dict[str, dict[str, Any]],
    approved: dict[str, dict[str, Any]],
) -> None:
    with TemporaryDirectory(prefix="kicad-published-readback-") as scratch:
        for name, asset in observed.items():
            if not _NAME.fullmatch(name):
                raise ValueError("invalid readback asset name")
            path = Path(scratch) / basename(name)
            client.download_asset(repo, asset["id"], path)
            if (
                path.is_symlink()
                or path.stat().st_size != approved[name]["size"]
                or digest(path) != approved[name]["sha256"]
            ):
                raise ValueError(f"existing asset bytes differ: {name}")


def _read_target(
    client: PublishedClient,
    repo: str,
    tag: str,
    source_commit: str,
    release_id: int,
    approved: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    release = client.release(repo, release_id)
    _check_identity(release, repo, tag, release_id)
    if client.tag_commit(repo, tag) != source_commit:
        raise ValueError("protected tag source differs")
    return release, _target_assets(release, approved)


def _upload_missing(
    *,
    read_target: Callable[[], tuple[dict[str, Any], dict[str, dict[str, Any]]]],
    upload_asset: Callable[[Path], None],
    staged: Path,
    preserved: dict[str, int],
    missing: list[str],
) -> list[str]:
    """Recheck the live inventory before each missing-only upload."""
    uploaded: list[str] = []
    for name in missing:
        fresh, current = read_target()
        if (
            fresh["immutable"]
            or {n: row["id"] for n, row in current.items() if n not in uploaded} != preserved
            or set(current) != set(preserved) | set(uploaded)
        ):
            raise ValueError("release assets changed during backfill; rerun from reviewed bytes")
        upload_asset(staged / basename(name))
        uploaded.append(name)
    return uploaded


def attach(
    client: PublishedClient,
    *,
    repo: str,
    tag: str,
    source_commit: str,
    source_root: Path,
    paths: list[Path],
    execute: bool = False,
) -> dict[str, object]:
    """Validate every existing target asset before any missing-only upload."""
    if repo not in _REPOSITORIES or not _TAG.fullmatch(tag) or not _SHA.fullmatch(source_commit):
        raise ValueError("invalid release repository, tag or source")
    with TemporaryDirectory(prefix="kicad-published-assets-") as scratch:
        staged = Path(scratch)
        _snapshot_local(paths, source_root, staged)
        approved = {x["name"]: x for x in manifest_for(staged, tag, source_commit)["assets"]}
        initial = client.release_by_tag(repo, tag)
        release_id = initial.get("id")
        if type(release_id) is not int or release_id <= 0:
            raise ValueError("invalid published release ID")
        _check_identity(initial, repo, tag, release_id)
        release, existing = _read_target(client, repo, tag, source_commit, release_id, approved)
        _verify_bytes(client, repo, existing, approved)
        preserved = {name: row["id"] for name, row in existing.items()}
        missing = sorted(set(approved) - set(existing))
        uploaded: list[str] = []
        if execute:
            if missing and release["immutable"]:
                raise ValueError("immutable release cannot receive missing assets")
            uploaded = _upload_missing(
                read_target=partial(
                    _read_target, client, repo, tag, source_commit, release_id, approved
                ),
                upload_asset=partial(client.upload_asset, repo, release_id),
                staged=staged,
                preserved=preserved,
                missing=missing,
            )
            _, final = _read_target(client, repo, tag, source_commit, release_id, approved)
            if set(final) != set(approved) or any(
                final[n]["id"] != i for n, i in preserved.items()
            ):
                raise ValueError("release asset inventory changed during readback")
            _verify_bytes(client, repo, final, approved)
        return {
            "releaseId": release_id,
            "preserved": sorted(preserved),
            "missing": missing,
            "uploaded": uploaded,
            "mode": "missing-only" if execute else "read-only",
            "publicationAuthorized": False,
            "exclusiveWriterVerified": False,
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("paths", type=Path, nargs="+")
    args = parser.parse_args()
    try:
        result = attach(
            PublishedGitHubCLI(),
            repo=args.repo,
            tag=args.tag,
            source_commit=args.source_commit,
            source_root=args.source_root,
            paths=args.paths,
            execute=args.execute,
        )
    except (OSError, ValueError) as exc:
        parser.exit(2, f"published release asset backfill blocked: {exc}\n")
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

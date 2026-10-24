"""Safely reconcile an existing GitHub draft Release without publishing it (#1179).

The default is read-only. --execute-uploads requires explicit release identity
confirmation and uploads *missing* assets by numeric ID (never clobbering). This program does
not create releases, edit release metadata, change tags, or publish drafts.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess  # nosec B404 - fixed gh CLI invocation; never uses a shell
import tempfile
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import quote

from scripts.check_draft_release_inventory import digest, verify
from scripts.plan_draft_release_retry import _approved_manifest, _draft_metadata, plan

_REPO = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_SHA = re.compile(r"^[0-9a-f]{40}$")


class DraftClient(Protocol):
    def release(self, repo: str, release_id: int) -> dict[str, Any]: ...

    def tag_commit(self, repo: str, tag: str) -> str: ...

    def download_asset(self, repo: str, asset_id: int, destination: Path) -> None: ...

    def upload_asset(self, repo: str, release_id: int, path: Path) -> None: ...


class GitHubCLI:
    @staticmethod
    def _gh() -> str:
        executable = shutil.which("gh")
        if executable is None:
            raise ValueError("GitHub CLI is not installed")
        return str(Path(executable).resolve())

    @staticmethod
    def _run(arguments: list[str]) -> bytes:
        # Trusted gh path is absolute; argv is passed directly without shell expansion.
        result = subprocess.run(  # nosec B603  # nosemgrep
            [GitHubCLI._gh(), *arguments], capture_output=True, check=False
        )
        if result.returncode:
            raise ValueError(f"GitHub CLI operation failed (exit {result.returncode})")
        return result.stdout

    def _json(self, route: str) -> dict[str, Any]:
        payload = json.loads(self._run(["api", route]))
        if not isinstance(payload, dict):
            raise ValueError("GitHub API response is not a JSON object")
        return payload

    def release(self, repo: str, release_id: int) -> dict[str, Any]:
        return self._json(f"repos/{repo}/releases/{release_id}")

    def tag_commit(self, repo: str, tag: str) -> str:
        obj = self._json(f"repos/{repo}/git/ref/tags/{tag}").get("object")
        for _ in range(5):
            if not isinstance(obj, dict):
                raise ValueError("invalid protected tag reference")
            sha, kind = obj.get("sha"), obj.get("type")
            if not isinstance(sha, str) or not _SHA.fullmatch(sha):
                raise ValueError("invalid protected tag object SHA")
            if kind == "commit":
                return sha
            if kind != "tag":
                raise ValueError("tag does not dereference to a commit")
            obj = self._json(f"repos/{repo}/git/tags/{sha}").get("object")
        raise ValueError("protected tag dereference exceeds maximum depth")

    def download_asset(self, repo: str, asset_id: int, destination: Path) -> None:
        with destination.open("xb") as output:
            # The only executable is trusted gh; user strings stay argv elements.
            result = subprocess.run(  # nosec B603  # nosemgrep
                [
                    self._gh(),
                    "api",
                    "-H",
                    "Accept: application/octet-stream",
                    f"repos/{repo}/releases/assets/{asset_id}",
                ],
                stdout=output,
                stderr=subprocess.PIPE,
                check=False,
            )
        if result.returncode:
            raise ValueError(f"GitHub draft asset download failed (exit {result.returncode})")

    def upload_asset(self, repo: str, release_id: int, path: Path) -> None:
        # Use the independently verified *numeric release ID*, never a tag lookup.
        # The upload API responds 422 to a name collision and never clobbers.
        url = (
            f"https://uploads.github.com/repos/{repo}/releases/{release_id}/assets"
            f"?name={quote(path.name, safe='')}"
        )
        response = json.loads(
            self._run(
                [
                    "api",
                    "-X",
                    "POST",
                    "-H",
                    "Content-Type: application/octet-stream",
                    "--input",
                    str(path),
                    url,
                ]
            )
        )
        if (
            not isinstance(response, dict)
            or type(response.get("id")) is not int
            or response["id"] <= 0
            or response.get("name") != path.name
            or response.get("state") != "uploaded"
        ):
            raise ValueError("GitHub asset upload did not confirm expected file")


def _valid_inputs(repo: str, release_id: int, tag: str, source_commit: str) -> None:
    if not _REPO.fullmatch(repo):
        raise ValueError("invalid GitHub repository identity")
    if type(release_id) is not int or release_id <= 0:
        raise ValueError("invalid GitHub release ID")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", tag):
        raise ValueError("invalid release tag")
    if not _SHA.fullmatch(source_commit):
        raise ValueError("invalid protected source commit")


def _downloaded_snapshot(
    client: DraftClient,
    repo: str,
    release: dict[str, Any],
    destination: Path,
    approved: set[str],
) -> None:
    assets = release.get("assets")
    if not isinstance(assets, list):
        raise ValueError("GitHub draft assets must be a list")
    seen_names: set[str] = set()
    seen_ids: set[int] = set()
    for asset in assets:
        if not isinstance(asset, dict):
            raise ValueError("invalid remote asset metadata")
        name, asset_id = asset.get("name"), asset.get("id")
        if not isinstance(name, str) or name not in approved or name in seen_names:
            raise ValueError("unknown or duplicate GitHub draft asset")
        if type(asset_id) is not int or asset_id <= 0 or asset_id in seen_ids:
            raise ValueError("invalid or duplicate GitHub draft asset ID")
        seen_names.add(name)
        seen_ids.add(asset_id)
        client.download_asset(repo, asset_id, destination / name)


def _reconcile_snapshot(
    client: DraftClient,
    *,
    repo: str,
    release_id: int,
    tag: str,
    source_commit: str,
    approved_dir: Path,
    manifest_path: Path,
    manifest_sha256: str,
    approved: set[str],
) -> tuple[dict[str, Any], dict[str, object]]:
    release = client.release(repo, release_id)
    tag_sha = client.tag_commit(repo, tag)
    _draft_metadata(release, repo, tag, source_commit, tag_sha)
    with tempfile.TemporaryDirectory(prefix="kicad-draft-1179-") as scratch:
        downloaded_dir = Path(scratch)
        _downloaded_snapshot(client, repo, release, downloaded_dir, approved)
        result = plan(
            approved_dir=approved_dir,
            downloaded_existing_dir=downloaded_dir,
            manifest_path=manifest_path,
            manifest_sha256=manifest_sha256,
            release=release,
            repo=repo,
            tag=tag,
            source_commit=source_commit,
            tag_commit=tag_sha,
        )
        if result["readyForFinalInventoryCheck"]:
            verify(
                directory=downloaded_dir,
                manifest_path=manifest_path,
                manifest_sha256=manifest_sha256,
                release=release,
                repository=repo,
                tag=tag,
                source_commit=source_commit,
                tag_commit=tag_sha,
            )
    return release, result


def stage(
    client: DraftClient,
    *,
    repo: str,
    release_id: int,
    tag: str,
    source_commit: str,
    approved_dir: Path,
    manifest_path: Path,
    manifest_sha256: str,
    execute_uploads: bool = False,
) -> dict[str, object]:
    _valid_inputs(repo, release_id, tag, source_commit)
    manifest = _approved_manifest(manifest_path, manifest_sha256, approved_dir, tag, source_commit)
    approved = {asset["name"]: asset for asset in manifest["assets"]}
    _, result = _reconcile_snapshot(
        client,
        repo=repo,
        release_id=release_id,
        tag=tag,
        source_commit=source_commit,
        approved_dir=approved_dir,
        manifest_path=manifest_path,
        manifest_sha256=manifest_sha256,
        approved=set(approved),
    )
    if not execute_uploads:
        return {**result, "mode": "read-only", "releaseId": release_id}
    # Recheck the live draft immediately before any write. Concurrent release
    # publication is still possible; callers MUST hold an exclusive release lock.
    _, fresh = _reconcile_snapshot(
        client,
        repo=repo,
        release_id=release_id,
        tag=tag,
        source_commit=source_commit,
        approved_dir=approved_dir,
        manifest_path=manifest_path,
        manifest_sha256=manifest_sha256,
        approved=set(approved),
    )
    missing = fresh["uploadMissingOnly"]
    if not isinstance(missing, list):
        raise ValueError("invalid draft upload plan")
    for name in missing:
        if not isinstance(name, str) or name not in approved:
            raise ValueError("invalid draft asset name in upload plan")
        item = approved[name]
        path = approved_dir / name
        if (
            path.is_symlink()
            or path.stat().st_size != item["size"]
            or digest(path) != item["sha256"]
        ):
            raise ValueError("approved asset changed before upload")
        client.upload_asset(repo, release_id, path)
    _, final = _reconcile_snapshot(
        client,
        repo=repo,
        release_id=release_id,
        tag=tag,
        source_commit=source_commit,
        approved_dir=approved_dir,
        manifest_path=manifest_path,
        manifest_sha256=manifest_sha256,
        approved=set(approved),
    )
    if not final["readyForFinalInventoryCheck"]:
        raise ValueError("draft still has missing assets after upload")
    return {**final, "mode": "uploaded-and-verified", "releaseId": release_id}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--release-id", type=int, required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--approved-assets", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--execute-uploads", action="store_true")
    parser.add_argument("--confirm-repository")
    parser.add_argument("--confirm-release-id", type=int)
    args = parser.parse_args()
    try:
        if args.execute_uploads and (
            args.confirm_repository != args.repo or args.confirm_release_id != args.release_id
        ):
            raise ValueError("write requires exact repository and release ID confirmation")
        outcome = stage(
            GitHubCLI(),
            repo=args.repo,
            release_id=args.release_id,
            tag=args.tag,
            source_commit=args.source_commit,
            approved_dir=args.approved_assets,
            manifest_path=args.manifest,
            manifest_sha256=args.manifest_sha256,
            execute_uploads=args.execute_uploads,
        )
    except (OSError, ValueError) as exc:
        parser.exit(2, f"draft Release staging: FAIL: {exc}\n")
    print(json.dumps(outcome, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

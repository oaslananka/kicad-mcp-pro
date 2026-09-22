"""Transfer and publish OpenCode repair changes without sharing write credentials."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import stat
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path, PurePosixPath
from typing import Any

MAX_CHANGED_FILES = 100
MAX_FILE_BYTES = 4 * 1024 * 1024
MAX_TOTAL_BYTES = 10 * 1024 * 1024
MANIFEST_VERSION = 1
_ALLOWED_MODES = {"100644", "100755", "120000"}


class PublishError(RuntimeError):
    """Raised when a repair bundle cannot be prepared or published safely."""


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise PublishError(f"missing required environment variable: {name}")
    return value


def _git(*args: str) -> bytes:
    env = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": os.environ.get("HOME", ""),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_SYSTEM": "/dev/null",
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_OPTIONAL_LOCKS": "0",
    }
    command = [
        "git",
        "-c",
        "core.fsmonitor=false",
        "-c",
        "core.hooksPath=/dev/null",
        *args,
    ]
    # GitHub-hosted runners provide Git on PATH; command arguments are fixed by this module.
    completed = subprocess.run(  # noqa: S607
        command,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )
    if completed.returncode != 0:
        message = completed.stderr.decode("utf-8", errors="replace").strip()
        raise PublishError(f"git command failed: {' '.join(command[1:])}: {message}")
    return completed.stdout


def _nul_list(payload: bytes) -> list[str]:
    return [
        item.decode("utf-8", errors="surrogateescape")
        for item in payload.split(b"\0")
        if item
    ]


def _safe_repo_path(relative: str) -> None:
    path = PurePosixPath(relative)
    if not relative or path.is_absolute() or ".." in path.parts:
        raise PublishError(f"unsafe repository-relative path: {relative!r}")


def _changed_paths() -> list[str]:
    tracked = _nul_list(
        _git(
            "diff",
            "--name-only",
            "--no-renames",
            "--no-ext-diff",
            "-z",
            "HEAD",
        )
    )
    untracked = _nul_list(_git("ls-files", "--others", "--exclude-standard", "-z"))
    paths = sorted(set(tracked) | set(untracked))
    if len(paths) > MAX_CHANGED_FILES:
        raise PublishError(
            f"repair changed {len(paths)} files; maximum allowed is {MAX_CHANGED_FILES}"
        )
    for path in paths:
        _safe_repo_path(path)
    return paths


def _base_mode(path: str) -> str | None:
    output = _git("ls-tree", "-z", "HEAD", "--", path)
    if not output:
        return None
    metadata = output.split(b"\t", 1)[0].decode("ascii", errors="strict")
    mode, kind, _sha = metadata.split(" ", 2)
    if kind != "blob" or mode not in _ALLOWED_MODES:
        raise PublishError(f"unsupported tracked object for {path}: {mode} {kind}")
    return mode


def _blob_payload(repo_root: Path, relative: str) -> tuple[str, bytes] | None:
    _safe_repo_path(relative)
    path = repo_root / relative
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None

    if stat.S_ISLNK(info.st_mode):
        data = os.readlink(path).encode("utf-8", errors="surrogateescape")
        return "120000", data
    if not stat.S_ISREG(info.st_mode):
        raise PublishError(f"unsupported changed path type: {relative}")

    resolved = path.resolve(strict=True)
    resolved.relative_to(repo_root)
    mode = "100755" if info.st_mode & stat.S_IXUSR else "100644"
    return mode, path.read_bytes()


def prepare_bundle(output_dir: Path) -> None:
    expected_head = _required("EXPECTED_HEAD_SHA")
    repo_root = Path.cwd().resolve()
    local_head = _git("rev-parse", "HEAD").decode("ascii").strip()
    if local_head != expected_head:
        raise PublishError(
            f"local HEAD changed during repair: expected {expected_head}, got {local_head}"
        )

    paths = _changed_paths()
    if output_dir.exists():
        raise PublishError(f"refusing to reuse existing bundle directory: {output_dir}")
    blobs_dir = output_dir / "blobs"
    blobs_dir.mkdir(parents=True)

    entries: list[dict[str, Any]] = []
    total = 0
    for index, relative in enumerate(paths):
        payload = _blob_payload(repo_root, relative)
        if payload is None:
            mode = _base_mode(relative)
            if mode is None:
                raise PublishError(
                    f"changed path disappeared without a tracked base: {relative}"
                )
            entries.append({"path": relative, "mode": mode, "deleted": True})
            continue

        mode, data = payload
        if len(data) > MAX_FILE_BYTES:
            raise PublishError(
                f"{relative} is {len(data)} bytes; maximum per-file size is {MAX_FILE_BYTES}"
            )
        total += len(data)
        if total > MAX_TOTAL_BYTES:
            raise PublishError(
                f"repair payload exceeds maximum total size of {MAX_TOTAL_BYTES} bytes"
            )

        blob_name = f"blobs/{index:04d}"
        (output_dir / blob_name).write_bytes(data)
        entries.append(
            {
                "path": relative,
                "mode": mode,
                "deleted": False,
                "blob": blob_name,
                "size": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
        )

    manifest = {
        "version": MANIFEST_VERSION,
        "expected_head": expected_head,
        "entries": entries,
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Prepared repair bundle for {len(entries)} changed files.")


def _load_bundle(bundle_dir: Path, expected_head: str) -> list[dict[str, Any]]:
    try:
        value = json.loads((bundle_dir / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PublishError(f"invalid repair manifest: {exc}") from exc

    if not isinstance(value, dict) or value.get("version") != MANIFEST_VERSION:
        raise PublishError("repair manifest version is missing or unsupported")
    if value.get("expected_head") != expected_head:
        raise PublishError("repair manifest does not match the expected pull-request head")

    raw_entries = value.get("entries")
    if not isinstance(raw_entries, list):
        raise PublishError("repair manifest entries must be a list")
    if len(raw_entries) > MAX_CHANGED_FILES:
        raise PublishError("repair manifest exceeds the changed-file limit")

    entries: list[dict[str, Any]] = []
    paths: list[str] = []
    total = 0
    root = bundle_dir.resolve()
    for index, raw in enumerate(raw_entries):
        if not isinstance(raw, dict):
            raise PublishError(f"repair manifest entry {index} must be an object")
        relative = raw.get("path")
        mode = raw.get("mode")
        deleted = raw.get("deleted")
        if not isinstance(relative, str):
            raise PublishError(f"repair manifest entry {index} has an invalid path")
        _safe_repo_path(relative)
        if mode not in _ALLOWED_MODES:
            raise PublishError(f"repair manifest entry {relative} has an invalid mode")
        if not isinstance(deleted, bool):
            raise PublishError(f"repair manifest entry {relative} has an invalid deletion flag")

        entry: dict[str, Any] = {"path": relative, "mode": mode, "deleted": deleted}
        if not deleted:
            blob_name = raw.get("blob")
            size = raw.get("size")
            digest = raw.get("sha256")
            if (
                not isinstance(blob_name, str)
                or not isinstance(size, int)
                or size < 0
                or not isinstance(digest, str)
                or len(digest) != 64
            ):
                raise PublishError(f"repair manifest entry {relative} has invalid blob metadata")
            blob_path = (bundle_dir / blob_name).resolve(strict=True)
            blob_path.relative_to(root)
            data = blob_path.read_bytes()
            if size != len(data) or size > MAX_FILE_BYTES:
                raise PublishError(f"repair blob size mismatch for {relative}")
            if hashlib.sha256(data).hexdigest() != digest:
                raise PublishError(f"repair blob checksum mismatch for {relative}")
            total += size
            if total > MAX_TOTAL_BYTES:
                raise PublishError("repair bundle exceeds the maximum total payload size")
            entry["data"] = data

        paths.append(relative)
        entries.append(entry)

    if paths != sorted(set(paths)):
        raise PublishError("repair manifest paths must be sorted and unique")
    return entries


class GitHub:
    def __init__(self, repository: str, token: str) -> None:
        self.repository = repository
        self.token = token
        self.base = f"https://api.github.com/repos/{repository}"

    def request(
        self,
        method: str,
        endpoint: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        # The base URL is a fixed HTTPS GitHub API origin; only repository API paths vary.
        request = urllib.request.Request(  # noqa: S310  # nosec B310
            f"{self.base}{endpoint}",
            data=data,
            method=method,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.token}",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "kicad-mcp-pro-opencode-publisher",
                **({"Content-Type": "application/json"} if data is not None else {}),
            },
        )
        try:
            with urllib.request.urlopen(  # noqa: S310  # nosec B310
                request,
                timeout=30,
            ) as response:
                body = response.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise PublishError(
                f"GitHub API request failed: {method} {endpoint}: "
                f"{exc.code} {exc.reason}: {detail}"
            ) from exc
        if not body:
            return {}
        value = json.loads(body)
        if not isinstance(value, dict):
            raise PublishError(f"GitHub API returned non-object JSON for {endpoint}")
        return value

    def comment(self, pr_number: str, body: str) -> None:
        self.request(
            "POST",
            f"/issues/{urllib.parse.quote(pr_number, safe='')}/comments",
            {"body": body},
        )


def _upload_blob(api: GitHub, data: bytes) -> str:
    response = api.request(
        "POST",
        "/git/blobs",
        {
            "content": base64.b64encode(data).decode("ascii"),
            "encoding": "base64",
        },
    )
    sha = response.get("sha")
    if not isinstance(sha, str) or not sha:
        raise PublishError("GitHub blob response did not contain a SHA")
    return sha


def publish_bundle(bundle_dir: Path) -> None:
    repository = _required("GITHUB_REPOSITORY")
    token = _required("GITHUB_TOKEN")
    pr_number = _required("PR_NUMBER")
    expected_head = _required("EXPECTED_HEAD_SHA")
    head_ref = _required("HEAD_REF")
    head_repo = _required("HEAD_REPO")
    run_url = _required("WORKFLOW_RUN_URL")

    if head_repo != repository:
        raise PublishError("refusing to publish to a forked pull request")

    entries = _load_bundle(bundle_dir, expected_head)
    api = GitHub(repository, token)
    encoded_ref = urllib.parse.quote(f"heads/{head_ref}", safe="/")
    remote_ref = api.request("GET", f"/git/ref/{encoded_ref}")
    remote_sha = remote_ref.get("object", {}).get("sha")
    if remote_sha != expected_head:
        raise PublishError(
            "pull request branch advanced while the repair was running; refusing to overwrite it"
        )

    if not entries:
        api.comment(
            pr_number,
            "OpenCode completed the requested repair but produced no repository changes. "
            f"Workflow: {run_url}",
        )
        print("No repository changes to publish.")
        return

    tree: list[dict[str, Any]] = []
    for entry in entries:
        if entry["deleted"]:
            sha: str | None = None
        else:
            sha = _upload_blob(api, entry["data"])
        tree.append(
            {
                "path": entry["path"],
                "mode": entry["mode"],
                "type": "blob",
                "sha": sha,
            }
        )

    base_commit = api.request("GET", f"/git/commits/{expected_head}")
    base_tree = base_commit.get("tree", {}).get("sha")
    if not isinstance(base_tree, str) or not base_tree:
        raise PublishError("base commit response did not contain a tree SHA")

    created_tree = api.request(
        "POST",
        "/git/trees",
        {"base_tree": base_tree, "tree": tree},
    )
    tree_sha = created_tree.get("sha")
    if not isinstance(tree_sha, str) or not tree_sha:
        raise PublishError("created tree response did not contain a SHA")

    commit = api.request(
        "POST",
        "/git/commits",
        {
            "message": f"fix: apply OpenCode repair for PR #{pr_number}",
            "tree": tree_sha,
            "parents": [expected_head],
        },
    )
    commit_sha = commit.get("sha")
    if not isinstance(commit_sha, str) or not commit_sha:
        raise PublishError("created commit response did not contain a SHA")

    api.request(
        "PATCH",
        f"/git/refs/{encoded_ref}",
        {"sha": commit_sha, "force": False},
    )

    paths = [entry["path"] for entry in entries]
    changed = "\n".join(f"- `{path}`" for path in paths[:25])
    suffix = "" if len(paths) <= 25 else f"\n- … and {len(paths) - 25} more"
    api.comment(
        pr_number,
        "OpenCode applied the requested repair in "
        f"`{commit_sha[:12]}`.\n\nChanged files:\n{changed}{suffix}\n\n"
        f"Workflow: {run_url}",
    )
    print(f"Published {len(paths)} changed files in {commit_sha}.")


def main() -> None:
    try:
        if len(sys.argv) != 3 or sys.argv[1] not in {"prepare", "publish"}:
            raise PublishError(
                "usage: opencode_publish.py {prepare|publish} BUNDLE_DIR"
            )
        bundle_dir = Path(sys.argv[2]).expanduser().resolve()
        if sys.argv[1] == "prepare":
            prepare_bundle(bundle_dir)
        else:
            publish_bundle(bundle_dir)
    except PublishError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()

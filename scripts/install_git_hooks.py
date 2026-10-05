#!/usr/bin/env python3
"""Install repository-local Lefthook shims without mutating global Git hook policy."""

from __future__ import annotations

import shutil
import subprocess  # nosec B404 -- controlled argv-only Git/Lefthook execution.
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _run(command: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # nosec B603  # nosemgrep
        command,
        cwd=ROOT,
        check=check,
        capture_output=True,
        text=True,
    )


def _git_output(arguments: list[str], *, scope_optional: bool = False) -> str:
    completed = _run(["git", *arguments], check=False)
    if completed.returncode != 0:
        if scope_optional and completed.returncode == 1:
            return ""
        sys.stderr.write(completed.stderr)
        raise SystemExit(completed.returncode)
    return completed.stdout.strip()


def _resolve_repo_path(raw: str) -> Path:
    path = Path(raw)
    if not path.is_absolute():
        path = ROOT / path
    return path.resolve()


def _lefthook_command(*arguments: str) -> list[str]:
    node = shutil.which("node")
    if node is None:
        raise RuntimeError("node is required; run ./scripts/bootstrap-dev.sh first")
    launcher = ROOT / "node_modules" / "lefthook" / "bin" / "index.js"
    if not launcher.is_file():
        raise RuntimeError("lefthook is not installed; run pnpm install first")
    return [node, str(launcher), *arguments]


def install() -> None:
    git_dir = _resolve_repo_path(_git_output(["rev-parse", "--git-dir"]))
    common_dir = _resolve_repo_path(_git_output(["rev-parse", "--git-common-dir"]))
    effective_hooks = _git_output(["config", "--get", "core.hooksPath"], scope_optional=True)
    local_hooks = _git_output(["config", "--local", "--get", "core.hooksPath"], scope_optional=True)

    if git_dir != common_dir:
        if effective_hooks:
            raise RuntimeError(
                "linked worktree has a custom core.hooksPath; refusing to rewrite shared Git "
                "configuration. Configure a worktree-specific hooks path explicitly before "
                "installing Lefthook."
            )
        command = _lefthook_command("install")
    else:
        expected_dir = (git_dir / "hooks").resolve()
        if local_hooks:
            current_dir = _resolve_repo_path(local_hooks)
            if current_dir != expected_dir:
                raise RuntimeError(
                    "repository-local core.hooksPath is custom; refusing to overwrite it. "
                    f"Current: {local_hooks!r}; expected: {expected_dir}"
                )
            command = _lefthook_command("install", "--force")
        elif effective_hooks:
            config_value = (
                ".git/hooks" if git_dir == (ROOT / ".git").resolve() else str(expected_dir)
            )
            _run(["git", "config", "--local", "core.hooksPath", config_value])
            print(
                "hooks: preserving global core.hooksPath and overriding it only for this repository"
            )
            command = _lefthook_command("install", "--force")
        else:
            command = _lefthook_command("install")

    completed = _run(command, check=False)
    sys.stdout.write(completed.stdout)
    sys.stderr.write(completed.stderr)
    if completed.returncode != 0:
        raise SystemExit(completed.returncode)

    verified = _run(_lefthook_command("check-install"), check=False)
    sys.stdout.write(verified.stdout)
    sys.stderr.write(verified.stderr)
    if verified.returncode != 0:
        raise SystemExit(verified.returncode)


def main() -> int:
    try:
        install()
    except RuntimeError as exc:
        print(f"hook installation failed: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

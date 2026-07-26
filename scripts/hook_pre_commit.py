"""Run fast staged-file checks for the Husky pre-commit hook."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from shutil import which


def _executable(name: str) -> str:
    resolved = which(name)
    if resolved is None:
        raise RuntimeError(f"Required executable not found on PATH: {name}")
    return resolved


def _run(command: list[str]) -> int:
    completed = subprocess.run(command, check=False)  # noqa: S603  # argv-only command.
    return completed.returncode


def _staged_python_files() -> list[str]:
    completed = subprocess.run(
        [_executable("git"), "diff", "--cached", "--name-only", "--diff-filter=ACMRTUXB"],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        sys.stderr.write(completed.stderr)
        raise SystemExit(completed.returncode)

    files: list[str] = []
    for raw_path in completed.stdout.splitlines():
        path = Path(raw_path)
        if path.suffix == ".py" and path.exists():
            files.append(raw_path)
    return files


def main() -> int:
    files = _staged_python_files()
    if not files:
        print("pre-commit: no staged Python files to check.")
        return 0

    commands = [
        [sys.executable, "-m", "ruff", "format", "--check", *files],
        [sys.executable, "-m", "ruff", "check", *files],
    ]
    for command in commands:
        exit_code = _run(command)
        if exit_code != 0:
            return exit_code
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Local workflow lint wrapper."""

from __future__ import annotations

import argparse
import pathlib
import shutil
import subprocess

import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
ACTIONLINT_COMMAND = ["actionlint"]


def _resolve_command(command: list[str]) -> list[str]:
    executable = shutil.which(command[0])
    if executable is None:
        msg = f"{command[0]} not found on PATH"
        raise RuntimeError(msg)
    return [executable, *command[1:]]


def _run(command: list[str]) -> None:
    result = subprocess.run(_resolve_command(command), cwd=REPO_ROOT, check=False)
    if result.returncode != 0:
        raise SystemExit(result.returncode)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--actionlint", action="store_true", help="Run actionlint as well.")
    args = parser.parse_args()

    workflow_dir = REPO_ROOT / ".github" / "workflows"
    workflows = [*sorted(workflow_dir.glob("*.yml")), *sorted(workflow_dir.glob("*.yaml"))]
    for path in workflows:
        yaml.safe_load(path.read_text(encoding="utf-8"))
    print(f"Parsed {len(workflows)} workflow file(s).")

    if args.actionlint:
        _run(ACTIONLINT_COMMAND)


if __name__ == "__main__":
    main()

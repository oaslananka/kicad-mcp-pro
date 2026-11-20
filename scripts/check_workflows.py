"""Local workflow lint wrapper."""

from __future__ import annotations

import argparse
import pathlib
import shutil
import subprocess
import sys

import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
ACTIONLINT_COMMAND = ["actionlint"]
# actionlint 1.7.12 predates GitHub's concurrency.queue support (upstream #657).
# This exception is safe only while every allowed queue is validated below.
_LEGACY_QUEUE_WARNING = 'unexpected key "queue" for "concurrency" section'


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


def _validate_workflow_concurrency(path: pathlib.Path, doc: dict) -> None:
    """Reject unapproved workflow-level and job-level concurrency queues."""
    concurrency = doc.get("concurrency")
    job_concurrency = [
        job.get("concurrency") for job in doc.get("jobs", {}).values() if isinstance(job, dict)
    ]
    for index, group in enumerate((concurrency, *job_concurrency)):
        if not isinstance(group, dict) or "queue" not in group:
            continue
        if (
            path.name != "publish-release.yml"
            or index != 0
            or group.get("group") != "publish-release-${{ github.repository }}"
            or group.get("cancel-in-progress") is not False
            or group.get("queue") != "max"
        ):
            raise ValueError(f"{path.name}: unapproved concurrency queue configuration")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--actionlint", action="store_true", help="Run actionlint as well.")
    args = parser.parse_args()

    workflow_dir = REPO_ROOT / ".github" / "workflows"
    workflows = [*sorted(workflow_dir.glob("*.yml")), *sorted(workflow_dir.glob("*.yaml"))]
    for path in workflows:
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(doc, dict):
            raise ValueError(f"{path.name}: workflow must be a mapping")
        _validate_workflow_concurrency(path, doc)
    print(f"Parsed {len(workflows)} workflow file(s).")

    if args.actionlint:
        # On Windows the actionlint/ShellCheck subprocess bridge can deadlock
        # on complex workflow scripts. Validate all YAML and expressions here;
        # the Linux GitHub Actions workflow-policy job still runs ShellCheck.
        command = [*ACTIONLINT_COMMAND, "-ignore", _LEGACY_QUEUE_WARNING]
        if sys.platform == "win32":
            command.append("-shellcheck=")
        # Single relative files avoid Windows absolute-path/auto-discovery stalls.
        for path in workflows:
            relative = path.relative_to(REPO_ROOT).as_posix()
            _run([*command, relative])


if __name__ == "__main__":
    main()

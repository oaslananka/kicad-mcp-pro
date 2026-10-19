"""Workflow security wrapper around zizmor."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
ZIZMOR_MIN_SEVERITIES = ("unknown", "informational", "low", "medium", "high")


def _canonical_min_severity(value: str) -> str:
    """Return a fixed zizmor severity token for an allowlisted CLI value."""
    match value:
        case "unknown":
            return "unknown"
        case "informational":
            return "informational"
        case "low":
            return "low"
        case "medium":
            return "medium"
        case "high":
            return "high"
        case _:
            raise ValueError(f"Unsupported zizmor minimum severity: {value!r}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--min-severity",
        default="high",
        choices=ZIZMOR_MIN_SEVERITIES,
    )
    args = parser.parse_args()
    min_severity = _canonical_min_severity(args.min_severity)

    binary = shutil.which("zizmor")
    if binary is None:
        print(
            "zizmor is required for workflow security checks. Install with "
            "`uv tool install zizmor` or see https://docs.zizmor.sh/installation/.",
            file=sys.stderr,
        )
        raise SystemExit(127)

    workflows_dir = (REPO_ROOT / ".github" / "workflows").resolve()
    if not workflows_dir.is_dir():
        print(f"Workflows directory not found: {workflows_dir}", file=sys.stderr)
        raise SystemExit(1)

    command = [
        binary,
        "--offline",
        "--min-severity",
        min_severity,
        str(workflows_dir),
    ]
    raise SystemExit(subprocess.run(command, check=False).returncode)  # nosec B603  # nosemgrep


if __name__ == "__main__":
    main()

"""Run pytest with a repository-external temporary directory."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

SUITES = {
    "unit": ["tests/unit/", "-q", "-m", "not benchmark"],
    "benchmark": ["tests/unit/test_regression_zoo.py", "-q", "-m", "benchmark"],
    "transport-contract": ["tests/unit/test_mcp_protocol_contract.py", "-q"],
    "gui": ["tests/gui/", "-q"],
    "full": [
        "tests/unit/",
        "tests/integration/",
        "tests/e2e/",
        "-q",
        "-m",
        "not benchmark",
        "--cov=kicad_mcp",
        "--cov=packages/kicad-plugin",
        "--cov-report=term-missing",
        "--cov-report=xml",
        "--cov-report=json",
        "--cov-fail-under=83",
        "--durations=25",
    ],
}


def _basetemp(suite: str) -> Path:
    temp_root = Path(tempfile.gettempdir()).resolve()
    path = Path(tempfile.mkdtemp(prefix=f"kicad-mcp-pro-pytest-{suite}-", dir=temp_root)).resolve()
    if temp_root != path and temp_root not in path.parents:
        raise RuntimeError(f"Refusing unsafe pytest temp path outside {temp_root}: {path}")
    return path


def main(argv: list[str]) -> int:
    suite = argv[1] if len(argv) > 1 else "full"
    if suite not in SUITES:
        valid = ", ".join(sorted(SUITES))
        print(f"Usage: python scripts/run_pytest.py <{valid}>", file=sys.stderr)
        return 2
    args = [*SUITES[suite], *argv[2:]]
    if suite == "full":
        workers = os.environ.get("KICAD_CI_PYTEST_WORKERS", "0")
        if workers not in {"0", "1", "2", "3", "4"}:
            print("KICAD_CI_PYTEST_WORKERS must be an integer between 0 and 4", file=sys.stderr)
            return 2
        if workers != "0":
            # One test file stays on one worker, avoiding within-file fixture races.
            args.extend(["-n", workers, "--dist=loadfile"])
    args.extend(["--basetemp", str(_basetemp(suite))])
    return pytest.main(args)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

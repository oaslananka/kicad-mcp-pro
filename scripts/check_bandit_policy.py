#!/usr/bin/env python3
"""Run Bandit while rejecting every non-reviewed medium/high finding."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
_EXPECTED_PATH = Path("src/kicad_mcp/evals/nvidia_nim_adapter.py")
_EXPECTED_TEST_ID = "B608"
_EXPECTED_PROMPT = "You are a tool-selection classifier for KiCad MCP Pro."


def _relative_path(filename: object, repo_root: Path) -> Path | None:
    if not isinstance(filename, str) or not filename:
        return None
    path = Path(filename)
    try:
        return path.resolve().relative_to(repo_root.resolve())
    except (OSError, ValueError):
        normalized = Path(filename.replace("\\", "/"))
        return normalized if not normalized.is_absolute() else None


def is_expected_false_positive(finding: dict[str, Any], repo_root: Path = ROOT) -> bool:
    """Allow only the reviewed B608 hit on the non-SQL classifier prompt."""
    relative = _relative_path(finding.get("filename"), repo_root)
    code = finding.get("code")
    return (
        relative == _EXPECTED_PATH
        and finding.get("test_id") == _EXPECTED_TEST_ID
        and isinstance(code, str)
        and _EXPECTED_PROMPT in code
    )


def _run_bandit(repo_root: Path) -> tuple[int, dict[str, Any]]:
    command = [
        sys.executable,
        "-m",
        "bandit",
        "-r",
        "src/",
        "-ll",
        "-s",
        "B104",
        "-f",
        "json",
        "-q",
    ]
    result = subprocess.run(
        command,
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode not in (0, 1):
        print(result.stderr, file=sys.stderr, end="")
        raise RuntimeError(f"Bandit failed with exit code {result.returncode}.")
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Bandit did not emit valid JSON.") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("Bandit JSON root must be an object.")
    return result.returncode, payload


def main() -> int:
    try:
        _, payload = _run_bandit(ROOT)
    except RuntimeError as exc:
        print(f"bandit policy check failed: {exc}", file=sys.stderr)
        return 2

    errors = payload.get("errors", [])
    if errors:
        print(json.dumps({"errors": errors}, indent=2, sort_keys=True), file=sys.stderr)
        return 2

    raw_results = payload.get("results", [])
    if not isinstance(raw_results, list):
        print("bandit policy check failed: results must be a list", file=sys.stderr)
        return 2
    findings = [item for item in raw_results if isinstance(item, dict)]
    unexpected = [item for item in findings if not is_expected_false_positive(item, ROOT)]
    allowed = len(findings) - len(unexpected)

    if unexpected:
        print(json.dumps({"unexpected_findings": unexpected}, indent=2, sort_keys=True))
        return 1

    print(f"Bandit passed: {allowed} reviewed false positive(s), 0 unexpected findings.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

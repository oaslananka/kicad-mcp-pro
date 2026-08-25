"""Enforce coverage for executable Python lines changed by a pull request."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import NamedTuple

_HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")
_MAX_UNCOVERED_DETAILS = 50
_COVERAGE_FILE = Path("coverage.json")
REPO_ROOT = Path(__file__).resolve().parents[1]


class PatchCoverage(NamedTuple):
    covered: int
    total: int
    uncovered: tuple[str, ...]

    @property
    def percent(self) -> float:
        if self.total == 0:
            return 100.0
        return (self.covered / self.total) * 100.0


def _normalize_path(value: str) -> str:
    return value.replace("\\", "/").removeprefix("./")


def _target_header(line: str) -> tuple[bool, str | None]:
    if not line.startswith("+++ "):
        return False, None
    raw_path = line[4:].split("\t", 1)[0]
    if raw_path == "/dev/null":
        return True, None
    return True, _normalize_path(raw_path.removeprefix("b/"))


def _record_target_line(line: str, target_line: int, changed_lines: set[int]) -> int:
    if line.startswith("+"):
        changed_lines.add(target_line)
        return target_line + 1
    if line.startswith(("-", "\\")):
        return target_line
    return target_line + 1


def parse_changed_lines(diff_text: str) -> dict[str, set[int]]:
    """Return added target-line numbers from a zero-context unified diff."""
    changed: dict[str, set[int]] = {}
    current_path: str | None = None
    target_line: int | None = None

    for line in diff_text.splitlines():
        is_header, header_path = _target_header(line)
        if is_header:
            current_path = header_path
            if current_path is not None:
                changed.setdefault(current_path, set())
            target_line = None
            continue

        match = _HUNK_RE.match(line)
        if match:
            target_line = int(match.group(1))
            continue

        if current_path is None or target_line is None:
            continue
        target_line = _record_target_line(line, target_line, changed[current_path])

    return {path: lines for path, lines in changed.items() if lines}


def _resolve_repo_file(path: Path) -> Path:
    if path != _COVERAGE_FILE:
        raise ValueError(f"--coverage-file must be the repository-local {_COVERAGE_FILE}")

    root = REPO_ROOT.resolve(strict=True)
    resolved = (root / _COVERAGE_FILE).resolve(strict=True)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"Coverage file is outside repository root: {resolved}") from exc
    if not resolved.is_file():
        raise ValueError(f"Coverage path is not a file: {resolved}")
    return resolved


def read_coverage_json(path: Path) -> dict[str, dict[int, int]]:
    """Read executable line hit counts from a coverage.py JSON report."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    result: dict[str, dict[int, int]] = {}
    for filename, details in payload.get("files", {}).items():
        normalized = _normalize_path(filename)
        lines = {int(number): 1 for number in details.get("executed_lines", [])}
        lines.update({int(number): 0 for number in details.get("missing_lines", [])})
        result[normalized] = lines
    return result


def measure_patch_coverage(
    coverage: dict[str, dict[int, int]],
    changed: dict[str, set[int]],
) -> PatchCoverage:
    """Measure only changed lines that coverage.py marks executable."""
    covered = 0
    total = 0
    uncovered: list[str] = []
    for path in sorted(changed):
        executable = coverage.get(path, {})
        for line_number in sorted(changed[path]):
            if line_number not in executable:
                continue
            total += 1
            if executable[line_number] > 0:
                covered += 1
            else:
                uncovered.append(f"{path}:{line_number}")
    return PatchCoverage(covered=covered, total=total, uncovered=tuple(uncovered))


def check_threshold(result: PatchCoverage, minimum: float) -> bool:
    return result.percent >= minimum


def _git_diff() -> str:
    command = [
        "git",
        "diff",
        "--unified=0",
        "--diff-filter=ACMR",
        "HEAD^1...HEAD",
        "--",
        "src/kicad_mcp",
    ]
    completed = subprocess.run(command, check=True, capture_output=True, text=True)
    return completed.stdout


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--coverage-file", type=Path, default=_COVERAGE_FILE)
    parser.add_argument("--min-percent", type=float, default=90.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if not 0.0 <= args.min_percent <= 100.0:
        print("--min-percent must be between 0 and 100", file=sys.stderr)
        return 2

    try:
        coverage_file = _resolve_repo_file(args.coverage_file)
        changed = parse_changed_lines(_git_diff())
        coverage = read_coverage_json(coverage_file)
    except (
        OSError,
        subprocess.CalledProcessError,
        TypeError,
        ValueError,
    ) as exc:
        print(f"Patch coverage evaluation failed: {exc}", file=sys.stderr)
        return 2

    result = measure_patch_coverage(coverage, changed)
    print(
        "Python patch coverage: "
        f"{result.percent:.2f}% ({result.covered}/{result.total} executable changed lines; "
        f"required {args.min_percent:.2f}%)"
    )
    if result.total == 0:
        print("No coverable changed lines under src/kicad_mcp; patch gate is not applicable.")
        return 0
    if check_threshold(result, args.min_percent):
        return 0

    print("Uncovered changed lines:", file=sys.stderr)
    for item in result.uncovered[:_MAX_UNCOVERED_DETAILS]:
        print(f"  {item}", file=sys.stderr)
    omitted = len(result.uncovered) - _MAX_UNCOVERED_DETAILS
    if omitted > 0:
        print(f"  ... and {omitted} more", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

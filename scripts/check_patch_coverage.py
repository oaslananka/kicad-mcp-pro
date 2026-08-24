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


def parse_changed_lines(diff_text: str) -> dict[str, set[int]]:
    """Return added target-line numbers from a zero-context unified diff."""
    changed: dict[str, set[int]] = {}
    current_path: str | None = None
    target_line: int | None = None

    for line in diff_text.splitlines():
        if line.startswith("+++ "):
            raw_path = line[4:].split("\t", 1)[0]
            if raw_path == "/dev/null":
                current_path = None
            else:
                current_path = _normalize_path(raw_path.removeprefix("b/"))
                changed.setdefault(current_path, set())
            target_line = None
            continue

        match = _HUNK_RE.match(line)
        if match:
            target_line = int(match.group(1))
            continue

        if current_path is None or target_line is None:
            continue
        if line.startswith("+"):
            changed[current_path].add(target_line)
            target_line += 1
        elif line.startswith("-"):
            continue
        elif line.startswith("\\"):
            continue
        else:
            target_line += 1

    return {path: lines for path, lines in changed.items() if lines}


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


def _git_diff(base_ref: str) -> str:
    command = [
        "git",
        "diff",
        "--unified=0",
        "--diff-filter=ACMR",
        f"{base_ref}...HEAD",
        "--",
        "src/kicad_mcp",
    ]
    completed = subprocess.run(command, check=True, capture_output=True, text=True)
    return completed.stdout


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-ref", required=True)
    parser.add_argument("--coverage-file", type=Path, default=Path("coverage.json"))
    parser.add_argument("--min-percent", type=float, default=90.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if not args.coverage_file.is_file():
        print(f"Patch coverage report not found: {args.coverage_file}", file=sys.stderr)
        return 2
    if not 0.0 <= args.min_percent <= 100.0:
        print("--min-percent must be between 0 and 100", file=sys.stderr)
        return 2

    try:
        changed = parse_changed_lines(_git_diff(args.base_ref))
        coverage = read_coverage_json(args.coverage_file)
    except (
        OSError,
        json.JSONDecodeError,
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

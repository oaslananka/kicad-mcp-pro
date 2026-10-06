#!/usr/bin/env python3
"""Aggregate versioned KiCad semantic differential records into one JSON report."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping
from pathlib import Path

from kicad_mcp.evals.semantic_differential import (
    DifferentialResult,
    aggregate_differential_results,
    render_differential_report_json,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--result", type=Path, action="append", required=True)
    parser.add_argument("--json-output", type=Path, required=True)
    return parser


def _load_mapping(path: Path) -> Mapping[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain one JSON object")
    return payload


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result_paths = [path.resolve() for path in args.result]
        json_output = args.json_output.resolve()
    except OSError as exc:
        print(f"semantic differential report failed: {exc}", file=sys.stderr)
        return 2

    if json_output in set(result_paths):
        print(
            "semantic differential report failed: output path must not overwrite input evidence",
            file=sys.stderr,
        )
        return 2

    try:
        results = [DifferentialResult.model_validate(_load_mapping(path)) for path in result_paths]
        report = aggregate_differential_results(results)
        rendered = render_differential_report_json(report)
    except (OSError, ValueError) as exc:
        print(f"semantic differential report failed: {exc}", file=sys.stderr)
        return 2

    try:
        json_output.parent.mkdir(parents=True, exist_ok=True)
        json_output.write_text(rendered, encoding="utf-8", newline="\n")
    except OSError as exc:
        print(f"semantic differential report failed: {exc}", file=sys.stderr)
        return 2
    print(f"wrote {args.json_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

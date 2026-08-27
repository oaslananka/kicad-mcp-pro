#!/usr/bin/env python3
"""Generate deterministic PCB task-outcome KPI reports from versioned evidence."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping
from pathlib import Path

from kicad_mcp.evals import (
    aggregate_task_outcomes,
    parse_attempt_record,
    parse_benchmark_contract,
    render_task_outcome_summary_json,
    render_task_outcome_summary_text,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--attempt", type=Path, action="append", required=True)
    parser.add_argument("--json-output", type=Path, required=True)
    parser.add_argument("--text-output", type=Path, required=True)
    return parser


def _load_mapping(path: Path) -> Mapping[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain one JSON object")
    return payload


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        contract_path = args.contract.resolve()
        attempt_paths = [path.resolve() for path in args.attempt]
        json_output = args.json_output.resolve()
        text_output = args.text_output.resolve()
    except OSError as exc:
        print(f"task outcome report failed: {exc}", file=sys.stderr)
        return 2

    if json_output == text_output:
        print("task outcome report failed: output paths must be different", file=sys.stderr)
        return 2
    input_paths = {contract_path, *attempt_paths}
    if json_output in input_paths or text_output in input_paths:
        print(
            "task outcome report failed: output paths must not overwrite input evidence",
            file=sys.stderr,
        )
        return 2

    try:
        contract = parse_benchmark_contract(_load_mapping(contract_path))
        attempts = [parse_attempt_record(_load_mapping(path)) for path in attempt_paths]
        summary = aggregate_task_outcomes(contract, attempts)
        json_report = render_task_outcome_summary_json(summary)
        text_report = render_task_outcome_summary_text(summary)
    except (OSError, ValueError) as exc:
        print(f"task outcome report failed: {exc}", file=sys.stderr)
        return 2

    try:
        json_output.parent.mkdir(parents=True, exist_ok=True)
        text_output.parent.mkdir(parents=True, exist_ok=True)
        json_output.write_text(json_report, encoding="utf-8", newline="\n")
        text_output.write_text(text_report, encoding="utf-8", newline="\n")
    except OSError as exc:
        print(f"task outcome report failed: {exc}", file=sys.stderr)
        return 2
    print(f"wrote {args.json_output} and {args.text_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

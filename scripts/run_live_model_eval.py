#!/usr/bin/env python3
"""Run a bounded provider-neutral tool-selection evaluation."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from kicad_mcp.capabilities import all_records
from kicad_mcp.evals.live_runner import (
    EvalConfigurationError,
    EvidenceSanitizationError,
    build_adapter,
    execute_evaluation,
    load_configurations,
    write_evidence,
)
from kicad_mcp.evals.tool_selection import EvalCase, load_cases, load_thresholds

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "evals/live/configurations.yaml"
DEFAULT_CASES = ROOT / "evals/tool_selection/cases.yaml"
DEFAULT_THRESHOLDS = ROOT / "evals/tool_selection/thresholds.yaml"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--configuration", required=True)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--thresholds", type=Path, default=DEFAULT_THRESHOLDS)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--case-tag")
    return parser


def _select_cases_by_tag(cases: list[EvalCase], tag: str | None) -> list[EvalCase]:
    """Return the canonical cases carrying ``tag`` or fail closed when none match."""
    if tag is None:
        return cases
    normalized = tag.strip()
    if not normalized:
        raise EvalConfigurationError("case tag must not be empty.")
    selected = [case for case in cases if normalized in case.tags]
    if not selected:
        raise EvalConfigurationError(f"No cases matched case tag {normalized!r}.")
    return selected


def main(argv: list[str] | None = None) -> int:
    """Execute the selected configuration and emit only a sanitized summary."""
    args = _parser().parse_args(argv)
    try:
        configurations = load_configurations(args.config)
        configuration = configurations.get(args.configuration)
        if configuration is None:
            raise EvalConfigurationError("Unknown configuration id.")
        cases = _select_cases_by_tag(load_cases(args.cases), args.case_tag)
        thresholds = load_thresholds(args.thresholds)
        records = all_records()
        report = execute_evaluation(
            cases,
            configuration,
            build_adapter(configuration),
            repeats=args.repeats,
            source_revision=args.source_revision,
            thresholds=thresholds,
            tool_tiers={name: record.tier for name, record in records.items()},
            checkpoint=lambda progress: write_evidence(args.output, progress),
        )
        write_evidence(args.output, report)
    except (EvalConfigurationError, EvidenceSanitizationError, OSError, ValueError):
        print("live-model eval failed: configuration, adapter, or evidence error", file=sys.stderr)
        return 2

    print(
        json.dumps(
            {
                "configuration": configuration.id,
                "pipeline_passed": bool(report.summary["pipeline_passed"]),
                "adapter_failures": int(report.summary["adapter_failures"]),
                "selection_failures": int(report.summary["selection_failures"]),
                "planned_observations": int(report.summary["planned_observations"]),
            },
            sort_keys=True,
        )
    )
    return 0 if bool(report.summary["pipeline_passed"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())

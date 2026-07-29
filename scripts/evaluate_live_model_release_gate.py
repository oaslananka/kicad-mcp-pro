#!/usr/bin/env python3
"""Evaluate downloaded sanitized live-model evidence against approved baselines."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from kicad_mcp.evals.release_gate import evaluate_release_gate, write_release_gate_report

ROOT = Path(__file__).resolve().parents[1]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, default=ROOT / "evals/live/baselines.yaml")
    parser.add_argument("--cases", type=Path, default=ROOT / "evals/tool_selection/cases.yaml")
    parser.add_argument(
        "--thresholds",
        type=Path,
        default=ROOT / "evals/tool_selection/thresholds.yaml",
    )
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        evidence_paths = sorted(args.evidence_root.rglob("evidence.json"))
        report = evaluate_release_gate(
            evidence_paths,
            baseline_path=args.baseline,
            cases_path=args.cases,
            thresholds_path=args.thresholds,
        )
        write_release_gate_report(args.output, report)
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        print("live-model release gate failed: invalid configuration or evidence", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "passed": bool(report["passed"]),
                "configuration_count": len(report["configurations"]),
                "safety_failures": len(report["classifications"]["safety_failures"]),
                "quality_failures": len(report["classifications"]["quality_failures"]),
                "infrastructure_failures": len(
                    report["classifications"]["infrastructure_failures"]
                ),
                "telemetry_unavailable": len(report["classifications"]["telemetry_unavailable"]),
            },
            sort_keys=True,
        )
    )
    return 0 if bool(report["passed"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Evaluate sanitized smoke artifacts under the risk-based release policy."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from kicad_mcp.evals.release_policy import load_baseline_metadata, load_release_policy
from kicad_mcp.evals.smoke_assurance import (
    evaluate_smoke_assurance,
    write_smoke_assurance_report,
)

ROOT = Path(__file__).resolve().parents[1]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--policy", type=Path, default=ROOT / "evals/live/release-policy.yaml")
    parser.add_argument("--baseline", type=Path, default=ROOT / "evals/live/baselines.yaml")
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        policy = load_release_policy(args.policy)
        baseline = load_baseline_metadata(args.baseline)
        evidence = sorted(args.evidence_root.glob("**/evidence.json"))
        statuses = sorted(args.evidence_root.glob("**/status.json"))
        report = evaluate_smoke_assurance(
            evidence,
            status_paths=statuses,
            require_status=True,
            required_configurations=baseline.required_configurations,
            minimum_successful_configurations=policy.minimum_smoke_configurations,
            expected_source_revision=args.source_revision,
        )
        write_smoke_assurance_report(args.output, report)
    except (OSError, TypeError, ValueError) as exc:
        print(f"live-model smoke assurance failed: {exc}", file=sys.stderr)
        return 2
    print(f"live-model smoke assurance: passed={report['passed']} degraded={report['degraded']}")
    return 0 if report["passed"] is True else 1


if __name__ == "__main__":
    raise SystemExit(main())

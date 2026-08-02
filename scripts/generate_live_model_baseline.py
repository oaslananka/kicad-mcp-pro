#!/usr/bin/env python3
"""Generate an auditable approved baseline from one sanitized full-gate report."""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

from kicad_mcp.evals.baseline_promotion import (
    BaselinePromotionError,
    generate_approved_baseline,
    write_approved_baseline,
)

ROOT = Path(__file__).resolve().parents[1]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--aggregate-report", type=Path, required=True)
    parser.add_argument("--workflow-run-id", type=int, required=True)
    parser.add_argument("--approved-at", type=date.fromisoformat, required=True)
    parser.add_argument(
        "--baseline-template", type=Path, default=ROOT / "evals/live/baselines.yaml"
    )
    parser.add_argument("--policy", type=Path, default=ROOT / "evals/live/release-policy.yaml")
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        baseline = generate_approved_baseline(
            aggregate_report_path=args.aggregate_report,
            baseline_template_path=args.baseline_template,
            policy_path=args.policy,
            repo_root=args.repo_root,
            workflow_run_id=args.workflow_run_id,
            approved_at=args.approved_at,
        )
        write_approved_baseline(args.output, baseline)
    except (OSError, TypeError, ValueError, BaselinePromotionError) as exc:
        print(f"live-model baseline generation failed: {exc}", file=sys.stderr)
        return 2
    print(f"wrote approved live-model baseline for {baseline['source_revision']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

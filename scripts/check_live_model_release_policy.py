#!/usr/bin/env python3
"""Classify live-model assurance for main pushes and release pull requests."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from kicad_mcp.evals.release_policy import (
    ReleasePolicyDecision,
    ReleasePolicyError,
    evaluate_noop_assurance,
    evaluate_push_assurance,
    evaluate_release_readiness,
)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POLICY = ROOT / "evals/live/release-policy.yaml"
DEFAULT_BASELINE = ROOT / "evals/live/baselines.yaml"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--github-output", type=Path)
    subparsers = parser.add_subparsers(dest="command", required=True)

    push = subparsers.add_parser("push")
    push.add_argument("--base-ref", required=True)
    push.add_argument("--head-ref", required=True)

    release = subparsers.add_parser("release")
    release.add_argument("--ref", default="HEAD")
    release.add_argument("--today", type=date.fromisoformat)

    noop = subparsers.add_parser("noop")
    noop.add_argument("--ref", default="HEAD")
    return parser


def _write_outputs(path: Path, decision: ReleasePolicyDecision) -> None:
    values = {
        "mode": decision.mode,
        "reason": decision.reason,
        "baseline_age_days": ""
        if decision.baseline_age_days is None
        else str(decision.baseline_age_days),
        "current_contract_digest": decision.current_contract_digest,
        "baseline_contract_digest": decision.baseline_contract_digest or "",
        "required_configurations": json.dumps(
            list(decision.required_configurations), separators=(",", ":")
        ),
    }
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        for key, value in values.items():
            handle.write(f"{key}={value}\n")


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "push":
            decision = evaluate_push_assurance(
                repo_root=args.repo_root,
                policy_path=args.policy,
                baseline_path=args.baseline,
                base_ref=args.base_ref,
                head_ref=args.head_ref,
            )
        elif args.command == "release":
            decision = evaluate_release_readiness(
                repo_root=args.repo_root,
                policy_path=args.policy,
                baseline_path=args.baseline,
                ref=args.ref,
                today=args.today,
            )
        else:
            decision = evaluate_noop_assurance(
                repo_root=args.repo_root,
                policy_path=args.policy,
                baseline_path=args.baseline,
                ref=args.ref,
            )
    except (OSError, ReleasePolicyError) as exc:
        print(f"live-model release policy failed: {exc}", file=sys.stderr)
        return 2

    print(json.dumps(decision.as_dict(), sort_keys=True, separators=(",", ":")))
    if args.github_output is not None:
        _write_outputs(args.github_output, decision)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

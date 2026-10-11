#!/usr/bin/env python3
"""Classify live-model assurance for main pushes and release pull requests."""

from __future__ import annotations

import argparse
import json
import os
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

try:
    from scripts.runtime_path_safety import approved_runtime_path
except ModuleNotFoundError:  # Direct `python scripts/foo.py` execution.
    from runtime_path_safety import approved_runtime_path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POLICY = ROOT / "evals/live/release-policy.yaml"
DEFAULT_BASELINE = ROOT / "evals/live/baselines.yaml"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--github-output", type=Path)
    parser.add_argument(
        "--require-ready",
        action="store_true",
        help="return non-zero when release readiness requires the protected full gate",
    )
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
    trusted_outputs: tuple[Path, ...] = ()
    configured_output = os.environ.get("GITHUB_OUTPUT")
    if configured_output:
        trusted_outputs = (Path(configured_output),)
    path = approved_runtime_path(path, extra_roots=trusted_outputs)
    values = {
        "mode": decision.mode,
        "reason": decision.reason,
        "baseline_age_days": ""
        if decision.baseline_age_days is None
        else str(decision.baseline_age_days),
        "current_contract_digest": decision.current_contract_digest,
        "baseline_contract_digest": decision.baseline_contract_digest or "",
        "release_base_ref": decision.release_base_ref or "",
        "release_contract_changed": (
            ""
            if decision.release_contract_changed is None
            else str(decision.release_contract_changed).lower()
        ),
        "required_configurations": json.dumps(
            list(decision.required_configurations), separators=(",", ":")
        ),
        "smoke_configurations": json.dumps(
            list(decision.smoke_configurations), separators=(",", ":")
        ),
    }
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        for key, value in values.items():
            handle.write(f"{key}={value}\n")


def _write_release_summary(decision: ReleasePolicyDecision) -> None:
    """Explain the policy result without changing the fail-closed exit status."""
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    summary = approved_runtime_path(Path(path), extra_roots=(Path(path),))
    baseline_age = (
        str(decision.baseline_age_days)
        if decision.baseline_age_days is not None
        else "not applicable"
    )
    lines = [
        "## Live-model release readiness",
        "",
        f"- **Decision:** `{decision.mode}` — `{decision.reason}`",
        f"- **Previous release:** `{decision.release_base_ref or 'unavailable'}`",
        f"- **Candidate contract SHA-256:** `{decision.current_contract_digest}`",
        f"- **Approved baseline SHA-256:** `{decision.baseline_contract_digest or 'unapproved'}`",
        f"- **Baseline age (days):** `{baseline_age}`",
        "",
        "### Agent-contract files changed since the last release",
        "",
    ]
    lines.extend(f"- `{name}`" for name in decision.contract_changed_paths)
    if not decision.contract_changed_paths:
        lines.append("- None")
    lines += ["", "### Next action", ""]
    if decision.mode == "full":
        lines.append(
            "**Blocked:** Run the protected **Live Model Release Gate** on `main`, "
            "review the complete evidence, then promote the approved baseline "
            "via a separate reviewed PR. Do **not** edit the digest manually or "
            "override required status checks."
        )
    elif decision.reason == "verified_unused_import_only_since_release":
        lines.append(
            "**Verified nonfunctional exception:** the only tracked contract diff "
            "removes an unused exception alias from an already imported module. "
            "Raw source digest remains distinct; no baseline evidence was modified. "
            "All regular release, packaging and security checks still apply."
        )
    else:
        lines.append("Release readiness passed under the configured contract policy.")
    with summary.open("a", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


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
    if args.command == "release":
        _write_release_summary(decision)
    if args.github_output is not None:
        _write_outputs(args.github_output, decision)
    if args.require_ready and decision.mode == "full":
        print(
            "live-model release readiness failed: protected full gate "
            "and baseline promotion required",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

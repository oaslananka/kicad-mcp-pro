#!/usr/bin/env python3
"""Generate or verify the maintained #942 stale-evidence escape report."""

from __future__ import annotations

import argparse
from pathlib import Path

from kicad_mcp.evals.stale_evidence_escape import (
    build_stale_evidence_escape_report,
    load_stale_evidence_escape_corpus,
    render_stale_evidence_escape_report_json,
)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CORPUS = ROOT / "evals/evidence_freshness/stale_escape_cases.json"
DEFAULT_REPORT = ROOT / "docs/evidence/stale-evidence-escape-report.json"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--output", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    corpus = load_stale_evidence_escape_corpus(args.corpus)
    report = build_stale_evidence_escape_report(corpus)
    rendered = render_stale_evidence_escape_report_json(report)

    if args.check:
        if not args.output.is_file() or args.output.read_text(encoding="utf-8") != rendered:
            raise SystemExit("stale-evidence escape report is stale; regenerate it")
        if not report.target_met or not report.all_expectations_met:
            raise SystemExit("stale-evidence escape target or golden expectations failed")
        print(
            "stale-evidence escape report verified: "
            f"{report.escape_count}/{report.stale_cases} escapes "
            f"({report.escape_rate:.3f}), target={report.target_escape_rate:.3f}"
        )
        return 0

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(rendered, encoding="utf-8")
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

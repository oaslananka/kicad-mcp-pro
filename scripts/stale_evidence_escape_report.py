#!/usr/bin/env python3
"""Generate or verify the maintained #942 stale-evidence escape report."""

from __future__ import annotations

import argparse
from pathlib import Path

from kicad_mcp.evals.stale_evidence_escape import (
    STALE_EVIDENCE_ESCAPE_CORPUS_PATH,
    build_stale_evidence_escape_report,
    load_stale_evidence_escape_corpus,
    render_stale_evidence_escape_report_json,
)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPORT = ROOT / "docs/evidence/stale-evidence-escape-report.json"


def main() -> int:
    if not STALE_EVIDENCE_ESCAPE_CORPUS_PATH.is_file():
        raise SystemExit("maintained stale-evidence corpus is missing")
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    corpus = load_stale_evidence_escape_corpus()
    report = build_stale_evidence_escape_report(corpus)
    rendered = render_stale_evidence_escape_report_json(report)

    if args.check:
        if not DEFAULT_REPORT.is_file() or DEFAULT_REPORT.read_text(encoding="utf-8") != rendered:
            raise SystemExit("stale-evidence escape report is stale; regenerate it")
        if not report.target_met or not report.all_expectations_met:
            raise SystemExit("stale-evidence escape target or golden expectations failed")
        print(
            "stale-evidence escape report verified: "
            f"{report.escape_count}/{report.stale_cases} escapes "
            f"({report.escape_rate:.3f}), target={report.target_escape_rate:.3f}"
        )
        return 0

    DEFAULT_REPORT.parent.mkdir(parents=True, exist_ok=True)
    DEFAULT_REPORT.write_text(rendered, encoding="utf-8")
    print(DEFAULT_REPORT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

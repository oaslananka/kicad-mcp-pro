#!/usr/bin/env python3
"""Score one canonical reference-board attempt and write its quality report."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from kicad_mcp.evals.reference_board_quality import (
    render_quality_score,
    score_reference_board_attempt,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle_root", type=Path)
    parser.add_argument("attempt_id")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        score = score_reference_board_attempt(args.bundle_root, args.attempt_id)
        root = args.bundle_root.resolve(strict=True)
        output = root / "attempts" / args.attempt_id / "board-quality-score.json"
        output.write_text(render_quality_score(score), encoding="utf-8", newline="\n")
    except (OSError, ValueError) as exc:
        print(f"reference-board scoring failed: {exc}", file=sys.stderr)
        return 2

    print(f"wrote {output}")
    return 0 if score.overall_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())

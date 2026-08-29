#!/usr/bin/env python3
"""Validate one publishable real-board reference-corpus bundle."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from kicad_mcp.evals import ReferenceCorpusError, validate_reference_board_bundle


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = validate_reference_board_bundle(args.bundle)
    except (OSError, ReferenceCorpusError, ValueError) as exc:
        print(f"reference corpus validation failed: {exc}", file=sys.stderr)
        return 2

    summary = result.summary
    print(
        "reference corpus valid "
        f"board={result.manifest.board_id} "
        f"attempts={summary.attempts_total} "
        f"successful={summary.successful_attempts} "
        f"failed={summary.failed_attempts} "
        f"infrastructure_invalid={summary.infrastructure_invalid_attempts}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

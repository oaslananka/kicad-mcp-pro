#!/usr/bin/env python3
"""Validate one publishable real-board reference-corpus bundle."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from kicad_mcp.evals import ReferenceCorpusError, validate_reference_board_bundle


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--bundle", type=Path)
    inputs.add_argument("--corpus-root", type=Path)
    return parser


def _validate_corpus_root(root: Path) -> int:
    """Report every published board version, including incomplete evidence.

    This is *not* an aggregate success rate: benchmark contracts can differ,
    and an incomplete board must never disappear from the visible denominator.
    """
    if root.is_symlink() or not root.is_dir():
        print("reference corpus root must be a real directory", file=sys.stderr)
        return 2

    board_count = 0
    complete_versions = 0
    incomplete_versions = 0
    for board in sorted(root.iterdir()):
        if (
            board.is_symlink()
            or not board.is_dir()
            or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", board.name) is None
        ):
            print("reference corpus contains an unsupported board entry", file=sys.stderr)
            return 2
        versions = sorted(board.iterdir())
        if not versions:
            print(f"board={board.name} status=incomplete reason=no benchmark versions")
            incomplete_versions += 1
            board_count += 1
            continue
        board_count += 1
        for version in versions:
            if (
                version.is_symlink()
                or not version.is_dir()
                or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", version.name) is None
            ):
                print("reference corpus contains an unsupported version entry", file=sys.stderr)
                return 2
            try:
                result = validate_reference_board_bundle(version)
            except (OSError, ReferenceCorpusError, ValueError):
                # Avoid printing user-supplied paths or raw evidence values.
                print(f"board={board.name} version={version.name} status=incomplete")
                incomplete_versions += 1
                continue
            if (
                result.manifest.board_id != board.name
                or result.manifest.benchmark_version != version.name
            ):
                print(f"board={board.name} version={version.name} status=incomplete")
                incomplete_versions += 1
                continue
            print(
                f"board={board.name} version={version.name} "
                f"status=validated attempts={result.summary.attempts_total} "
                f"successful={result.summary.successful_attempts} "
                f"failed={result.summary.failed_attempts} "
                f"infrastructure_invalid={result.summary.infrastructure_invalid_attempts}"
            )
            complete_versions += 1
    print(
        f"corpus boards={board_count} validated_versions={complete_versions} "
        f"incomplete_versions={incomplete_versions}"
    )
    return 0 if board_count > 0 and incomplete_versions == 0 else 2


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.corpus_root is not None:
        return _validate_corpus_root(args.corpus_root)
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

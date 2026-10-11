#!/usr/bin/env python3
"""Validate real-board corpus evidence without mistaking readiness for task success."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from kicad_mcp.evals import ReferenceCorpusError, validate_reference_board_bundle

READINESS_SCHEMA = "reference-corpus-readiness.v1"
_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--bundle", type=Path)
    inputs.add_argument("--corpus-root", type=Path)
    parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="Machine-readable fail-closed corpus status (not an aggregate KPI)",
    )
    return parser


def _format_record(record: dict[str, Any]) -> str:
    message = f"board={record['board_id']}"
    if "version" in record:
        message += f" version={record['version']}"
    message += f" status={record['status']}"
    if record["status"] == "validated":
        return (
            f"{message} attempts={record['attempts']}"
            f" successful={record['successful']}"
            f" failed={record['failed']}"
            f" infrastructure_invalid={record['infrastructure_invalid']}"
        )
    if record.get("reason") == "no_benchmark_versions":
        message += " reason=no benchmark versions"
    return message


def _corpus_status(board_count: int, incomplete: int, error: str | None) -> str:
    if error:
        return "invalid_corpus"
    if not board_count or incomplete:
        return "incomplete"
    return "validated"


def _emit_corpus(
    records: list[dict[str, Any]],
    *,
    board_count: int,
    json_output: bool,
    error: str | None = None,
) -> int:
    """Retain every board/version without inventing a success denominator."""
    complete_versions = sum(record["status"] == "validated" for record in records)
    incomplete_versions = len(records) - complete_versions
    status = _corpus_status(board_count, incomplete_versions, error)

    if json_output:
        payload: dict[str, Any] = {
            "schema_version": READINESS_SCHEMA,
            "status": status,
            "boards": records,
            "summary": {
                "boards": board_count,
                "validated_versions": complete_versions,
                "incomplete_versions": incomplete_versions,
            },
        }
        if error:
            payload["error"] = error
        print(json.dumps(payload, sort_keys=True))
    else:
        if error:
            print(error.replace("_", " "), file=sys.stderr)
        for record in records:
            print(_format_record(record))
        if not error:
            print(
                f"corpus boards={board_count} validated_versions={complete_versions} "
                f"incomplete_versions={incomplete_versions}"
            )
    return 0 if status == "validated" else 2


def _version_record(board: Path, version: Path) -> dict[str, Any]:
    record: dict[str, Any] = {"board_id": board.name, "version": version.name}
    try:
        result = validate_reference_board_bundle(version)
    except (OSError, ReferenceCorpusError, ValueError):
        record.update(status="incomplete", reason="missing_or_invalid_evidence")
        return record
    if result.manifest.board_id != board.name or result.manifest.benchmark_version != version.name:
        record.update(status="incomplete", reason="manifest_identity_mismatch")
        return record
    record.update(
        status="validated",
        attempts=result.summary.attempts_total,
        successful=result.summary.successful_attempts,
        failed=result.summary.failed_attempts,
        infrastructure_invalid=result.summary.infrastructure_invalid_attempts,
    )
    return record


def _board_records(board: Path) -> list[dict[str, Any]]:
    if board.is_symlink() or not board.is_dir() or _SAFE_ID.fullmatch(board.name) is None:
        raise ValueError("reference_corpus_contains_an_unsupported_board_entry")
    versions = sorted(board.iterdir())
    if not versions:
        return [{"board_id": board.name, "status": "incomplete", "reason": "no_benchmark_versions"}]
    if any(
        version.is_symlink() or not version.is_dir() or _SAFE_ID.fullmatch(version.name) is None
        for version in versions
    ):
        raise ValueError("reference_corpus_contains_an_unsupported_version_entry")
    return [_version_record(board, version) for version in versions]


def _validate_corpus_root(root: Path, *, json_output: bool = False) -> int:
    """Report all boards, even if no attempted design meets release gates."""
    if root.is_symlink() or not root.is_dir():
        return _emit_corpus(
            [],
            board_count=0,
            json_output=json_output,
            error="reference_corpus_root_must_be_a_real_directory",
        )

    records: list[dict[str, Any]] = []
    board_count = 0
    for board in sorted(root.iterdir()):
        # Only this canonical, regular documentation file is not a board.
        # Do not permit symlinks or arbitrary extra files to evade auditing.
        if board.name == "README.md" and board.is_file() and not board.is_symlink():
            continue
        try:
            board_records = _board_records(board)
        except ValueError as exc:
            # _board_records raises only constant, public-safe reason codes.
            return _emit_corpus(
                records,
                board_count=board_count,
                json_output=json_output,
                error=str(exc),
            )
        records.extend(board_records)
        board_count += 1
    return _emit_corpus(records, board_count=board_count, json_output=json_output)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.corpus_root is not None:
        return _validate_corpus_root(args.corpus_root, json_output=args.format == "json")
    try:
        result = validate_reference_board_bundle(args.bundle)
    except (OSError, ReferenceCorpusError, ValueError) as exc:
        if args.format == "json":
            print(json.dumps({"schema_version": READINESS_SCHEMA, "status": "incomplete"}))
        else:
            print(f"reference corpus validation failed: {exc}", file=sys.stderr)
        return 2

    summary = result.summary
    if args.format == "json":
        print(
            json.dumps(
                {
                    "schema_version": READINESS_SCHEMA,
                    "status": "validated",
                    "board_id": result.manifest.board_id,
                    "benchmark_version": result.manifest.benchmark_version,
                    "attempts": summary.attempts_total,
                    "successful": summary.successful_attempts,
                    "failed": summary.failed_attempts,
                    "infrastructure_invalid": summary.infrastructure_invalid_attempts,
                },
                sort_keys=True,
            )
        )
    else:
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

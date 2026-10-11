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


def _emit_corpus(
    records: list[dict[str, Any]],
    *,
    board_count: int,
    complete_versions: int,
    incomplete_versions: int,
    json_output: bool,
    error: str | None = None,
) -> int:
    """Report all observed versions without fabricating a success denominator."""
    if json_output:
        payload = {
            "schema_version": READINESS_SCHEMA,
            "status": "invalid_corpus"
            if error
            else ("validated" if board_count and not incomplete_versions else "incomplete"),
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
            message = f"board={record['board_id']}"
            if "version" in record:
                message += f" version={record['version']}"
            message += f" status={record['status']}"
            if record["status"] == "validated":
                message += (
                    f" attempts={record['attempts']}"
                    f" successful={record['successful']}"
                    f" failed={record['failed']}"
                    f" infrastructure_invalid={record['infrastructure_invalid']}"
                )
            elif record.get("reason") == "no_benchmark_versions":
                message += " reason=no benchmark versions"
            print(message)
        if not error:
            print(
                f"corpus boards={board_count} validated_versions={complete_versions} "
                f"incomplete_versions={incomplete_versions}"
            )
    return 0 if not error and board_count > 0 and incomplete_versions == 0 else 2


def _validate_corpus_root(root: Path, *, json_output: bool = False) -> int:
    """Account for every board version; no aggregate success claim."""
    if root.is_symlink() or not root.is_dir():
        return _emit_corpus(
            [],
            board_count=0,
            complete_versions=0,
            incomplete_versions=0,
            json_output=json_output,
            error="reference_corpus_root_must_be_a_real_directory",
        )

    records: list[dict[str, Any]] = []
    board_count = complete_versions = incomplete_versions = 0
    for board in sorted(root.iterdir()):
        if board.is_symlink() or not board.is_dir() or _SAFE_ID.fullmatch(board.name) is None:
            return _emit_corpus(
                records,
                board_count=board_count,
                complete_versions=complete_versions,
                incomplete_versions=incomplete_versions,
                json_output=json_output,
                error="reference_corpus_contains_an_unsupported_board_entry",
            )
        versions = sorted(board.iterdir())
        board_count += 1
        if not versions:
            records.append(
                {"board_id": board.name, "status": "incomplete", "reason": "no_benchmark_versions"}
            )
            incomplete_versions += 1
            continue
        for version in versions:
            if (
                version.is_symlink()
                or not version.is_dir()
                or _SAFE_ID.fullmatch(version.name) is None
            ):
                return _emit_corpus(
                    records,
                    board_count=board_count,
                    complete_versions=complete_versions,
                    incomplete_versions=incomplete_versions,
                    json_output=json_output,
                    error="reference_corpus_contains_an_unsupported_version_entry",
                )
            record: dict[str, Any] = {"board_id": board.name, "version": version.name}
            try:
                result = validate_reference_board_bundle(version)
            except (OSError, ReferenceCorpusError, ValueError):
                record.update(status="incomplete", reason="missing_or_invalid_evidence")
            else:
                if (
                    result.manifest.board_id != board.name
                    or result.manifest.benchmark_version != version.name
                ):
                    record.update(status="incomplete", reason="manifest_identity_mismatch")
                else:
                    record.update(
                        status="validated",
                        attempts=result.summary.attempts_total,
                        successful=result.summary.successful_attempts,
                        failed=result.summary.failed_attempts,
                        infrastructure_invalid=result.summary.infrastructure_invalid_attempts,
                    )
            records.append(record)
            if record["status"] == "validated":
                complete_versions += 1
            else:
                incomplete_versions += 1
    return _emit_corpus(
        records,
        board_count=board_count,
        complete_versions=complete_versions,
        incomplete_versions=incomplete_versions,
        json_output=json_output,
    )


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

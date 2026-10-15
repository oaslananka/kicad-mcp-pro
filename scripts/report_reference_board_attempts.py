#!/usr/bin/env python3
"""Read-only, fail-closed attempt-level scoreboard for reviewed PCB benchmarks.

Uses the existing validated corpus and canonical task outcome scorer. A partial
corpus is never silently turned into a publishable global PCB success rate.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from kicad_mcp.evals import ReferenceCorpusError, validate_reference_board_bundle
from kicad_mcp.evals.reference_board_quality import score_reference_board_attempt

SCHEMA = "reference-board-attempt-scoreboard.v1"
_BOARD = re.compile(r"[a-z0-9][a-z0-9-]{0,63}\Z")
_VERSION = re.compile(r"v[1-9]\d*\Z", re.ASCII)


def _score_and_format_attempts(
    root: Path,
    board: str,
    version: str,
    records: list[Any],
) -> list[dict[str, Any]]:
    attempts: list[dict[str, Any]] = []
    for attempt in sorted(records, key=lambda record: record.attempt_id):
        # Recompute rather than trusting cached score JSON. Importantly, this
        # score is a *quality diagnostic*, never task success by itself.
        quality = score_reference_board_attempt(root, attempt.attempt_id)
        if (
            quality.board_id,
            quality.benchmark_version,
            quality.attempt_id,
            quality.source_revision,
        ) != (
            board,
            version,
            attempt.attempt_id,
            attempt.source_revision,
        ):
            raise ReferenceCorpusError("recomputed quality identity mismatch")
        attempts.append(
            {
                "attempt_id": attempt.attempt_id,
                "classification": attempt.classification,
                "failure_category": attempt.failure_category,
                "failure_reason_code": attempt.failure_reason_code,
                "task_id": attempt.task_id,
                "source_revision": attempt.source_revision,
                "agent": attempt.agent,
                "provider": attempt.provider,
                "model": attempt.model,
                "erc": next(
                    (v.disposition for v in attempt.validations if v.kind == "erc"), "not_recorded"
                ),
                "drc": next(
                    (v.disposition for v in attempt.validations if v.kind == "drc"), "not_recorded"
                ),
                "quality": {
                    "passed_required_rules": quality.passed_required_rule_count,
                    "required_rules": quality.required_rule_count,
                    "score_percent": quality.quality_score_percent,
                    "all_rules_passed": quality.overall_pass,
                },
            }
        )
    return attempts


def _summarize_valid_bundle(root: Path, board: str, version: str) -> dict[str, Any]:
    result = validate_reference_board_bundle(root)
    if (result.manifest.board_id, result.manifest.benchmark_version) != (board, version):
        raise ReferenceCorpusError("manifest identity mismatch")
    summary = result.summary
    if summary.attempts_total != len(result.manifest.attempts):
        raise ReferenceCorpusError("manifest attempt count mismatch")
    indexed = {entry.attempt_id for entry in result.manifest.attempts}
    if indexed != {record.attempt_id for record in result.attempts}:
        raise ReferenceCorpusError("manifest attempt identities mismatch")
    attempts = _score_and_format_attempts(root, board, version, result.attempts)
    classifications = Counter(record.classification for record in result.attempts)
    if sum(classifications.values()) != summary.attempts_total:
        raise ReferenceCorpusError("attempt classification count mismatch")
    return {
        "board_id": board,
        "benchmark_version": version,
        "status": "validated",
        "benchmark_id": result.manifest.benchmark_id,
        "reference_inputs_digest": result.manifest.reference_inputs_digest,
        "attempts_total": summary.attempts_total,
        "valid_attempts": summary.valid_attempts,
        "infrastructure_invalid_attempts": summary.infrastructure_invalid_attempts,
        "successful_attempts": summary.successful_attempts,
        "failed_attempts": summary.failed_attempts,
        "classifications": dict(sorted(classifications.items())),
        "task_success": summary.task_success.model_dump(mode="json"),
        "required_drc_execution": summary.required_drc_execution.model_dump(mode="json"),
        "manufacturing_reproducibility": summary.manufacturing_reproducibility.model_dump(
            mode="json"
        ),
        "attempt_history": attempts,
    }


def _board_version(root: Path, board: str, version: str) -> dict[str, Any]:
    try:
        if root.is_symlink() or not root.is_dir():
            raise ReferenceCorpusError("invalid board version root")
        return _summarize_valid_bundle(root, board, version)
    except (OSError, ValueError, ReferenceCorpusError):
        # Publish no denominator from an unverified bundle, and never leak a
        # malformed evidence payload or local filesystem exception message.
        return {
            "board_id": board,
            "benchmark_version": version,
            "status": "incomplete",
            "reason_code": "missing_or_invalid_evidence",
        }


def _valid_entry(path: Path, regex: re.Pattern[str]) -> bool:
    return path.is_dir() and not path.is_symlink() and bool(regex.fullmatch(path.name))


def _collect_corpus_versions(root: Path) -> list[dict[str, Any]]:
    """Enumerate identities without silently skipping malformed evidence."""
    versions: list[dict[str, Any]] = []
    for board in sorted(root.iterdir()):
        if board.name == "README.md" and board.is_file() and not board.is_symlink():
            continue
        if not _valid_entry(board, _BOARD):
            raise ValueError("invalid board")
        entries = sorted(board.iterdir())
        if not entries:
            versions.append(
                {
                    "board_id": board.name,
                    "status": "incomplete",
                    "reason_code": "no_benchmark_versions",
                }
            )
        for version in entries:
            if not _valid_entry(version, _VERSION):
                raise ValueError("invalid version")
            versions.append(_board_version(version, board.name, version.name))
    return versions


def audit_corpus(root: Path) -> dict[str, Any]:
    """Inventory *all* versions before deciding if anything is publishable."""
    if root.is_symlink() or not root.is_dir():
        return {
            "schema_version": SCHEMA,
            "status": "invalid_corpus",
            "reason_code": "invalid_corpus_root",
        }
    try:
        versions = _collect_corpus_versions(root)
    except (OSError, ValueError):
        return {
            "schema_version": SCHEMA,
            "status": "invalid_corpus",
            "reason_code": "unsupported_corpus_entry",
        }

    incomplete = sum(v["status"] != "validated" for v in versions)
    return {
        "schema_version": SCHEMA,
        "status": "validated" if versions and not incomplete else "incomplete",
        "board_versions": versions,
        "summary": {
            "board_versions_total": len(versions),
            "validated_versions": len(versions) - incomplete,
            "incomplete_versions": incomplete,
            # Different board/version benchmark contracts MUST NOT be silently
            # pooled into an attractive but invalid aggregate success rate.
            "cross_benchmark_success_rate": None,
            "cross_benchmark_kpi_publishable": False,
        },
    }


def audit_bundle(root: Path) -> dict[str, Any]:
    if not _valid_entry(root, _VERSION) or not _valid_entry(root.parent, _BOARD):
        return {
            "schema_version": SCHEMA,
            "status": "invalid_corpus",
            "reason_code": "invalid_bundle_identity",
        }
    entry = _board_version(root, root.parent.name, root.name)
    return {"schema_version": SCHEMA, "status": entry["status"], "board_version": entry}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--corpus-root", type=Path)
    source.add_argument("--bundle", type=Path)
    args = parser.parse_args(argv)
    report = (
        audit_corpus(args.corpus_root)
        if args.corpus_root is not None
        else audit_bundle(args.bundle)
    )
    print(json.dumps(report, sort_keys=True, ensure_ascii=False))
    return 0 if report["status"] == "validated" else 2


if __name__ == "__main__":
    sys.exit(main())

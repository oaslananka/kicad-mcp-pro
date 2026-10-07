"""Native KiCad DRC semantic differential comparison helpers."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from pathlib import Path
from typing import cast

from ..validation.drc_report import normalize_report_severity, report_entries
from ..validation.drc_runner import DrcRunStatus, classify_drc_report
from .semantic_differential import (
    DifferentialLane,
    DifferentialResult,
    classify_differential_result,
)

DrcClassifier = Callable[[object], tuple[DrcRunStatus, str | None]]
type FindingSignature = tuple[str, str, str]
type DrcProjection = tuple[str, tuple[FindingSignature, ...]]

DRC_AUTHORITY = "kicad-cli:pcb-drc-json"
DRC_OPERATION = "drc.findings-and-severities"
DRC_COMPARISON_METHOD = "finding-bucket-type-severity-sha256.v1"
_FINDING_BUCKETS = ("violations", "unconnected_items")
_FIXTURE_INPUT_SUFFIXES = frozenset({".kicad_pcb", ".kicad_pro", ".kicad_dru"})


def _sha256_projection(projection: DrcProjection) -> str:
    outcome, findings = projection
    encoded = json.dumps(
        {
            "outcome": outcome,
            "findings": [
                {"bucket": bucket, "type": issue_type, "severity": severity}
                for bucket, issue_type, severity in findings
            ],
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def hash_fixture_tree(path: Path) -> str:
    """Hash one fixture file/tree deterministically by relative path and content."""
    resolved = path.resolve(strict=True)
    if resolved.is_file():
        root = resolved.parent
        files = [resolved]
    elif resolved.is_dir():
        root = resolved
        files = sorted(
            item
            for item in resolved.rglob("*")
            if item.is_file() and item.suffix in _FIXTURE_INPUT_SUFFIXES
        )
    else:
        raise ValueError(f"Fixture path is not a file or directory: {path}")
    if not files:
        raise ValueError(f"Fixture path contains no files: {path}")

    digest = hashlib.sha256()
    for item in files:
        relative = item.relative_to(root).as_posix().encode("utf-8")
        content = item.read_bytes()
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return f"sha256:{digest.hexdigest()}"


def _native_severity(value: object) -> str:
    normalized = str(value or "error").casefold()
    return "warning" if normalized in {"warning", "warn", "marginal"} else "error"


def _native_projection(report: object) -> DrcProjection:
    """Project raw KiCad JSON without using MCP Pro's DRC parser helpers."""
    if not isinstance(report, dict):
        raise ValueError("Native DRC report root must be a JSON object.")

    signatures: list[FindingSignature] = []
    for bucket in _FINDING_BUCKETS:
        if bucket not in report:
            if bucket == "violations":
                raise ValueError("Native DRC report is missing required field 'violations'.")
            continue
        raw_entries = report[bucket]
        if not isinstance(raw_entries, list):
            raise ValueError(f"Native DRC report field '{bucket}' must be a list.")
        if any(not isinstance(entry, dict) for entry in raw_entries):
            raise ValueError(f"Native DRC report field '{bucket}' must contain only objects.")
        for raw_entry in raw_entries:
            entry = cast(dict[str, object], raw_entry)
            signatures.append(
                (
                    bucket,
                    str(entry.get("type") or bucket),
                    _native_severity(entry.get("severity")),
                )
            )

    findings = tuple(sorted(signatures))
    return ("pass" if not findings else "fail", findings)


def _custom_projection(
    report: object,
    classifier: DrcClassifier,
) -> tuple[bool | None, DrcProjection, str | None]:
    """Project the same report through MCP Pro's production parser semantics."""
    status, detail = classifier(report)
    if status not in {"clean", "findings"}:
        raise ValueError(detail or f"MCP Pro DRC parser returned {status}")

    typed_report = cast(dict[str, object], report)
    signatures = tuple(
        sorted(
            (
                bucket,
                str(entry.get("type") or bucket),
                normalize_report_severity(entry.get("severity")),
            )
            for bucket in _FINDING_BUCKETS
            for entry in report_entries(typed_report, bucket)
        )
    )
    custom_pass = status == "clean"
    return custom_pass, ("pass" if custom_pass else "fail", signatures), detail


def compare_drc_report_file(
    *,
    report_path: Path,
    fixture_path: Path,
    source_sha: str,
    lane: DifferentialLane,
    kicad_version: str,
    fixture_id: str,
    custom_classifier: DrcClassifier = classify_drc_report,
    native_authority_available: bool = True,
) -> DifferentialResult:
    """Compare raw native DRC authority with MCP Pro's production DRC semantics."""
    fixture_hash = hash_fixture_tree(fixture_path)
    if not native_authority_available:
        return classify_differential_result(
            source_sha=source_sha,
            lane=lane,
            kicad_version=kicad_version,
            fixture_id=fixture_id,
            fixture_hash=fixture_hash,
            operation=DRC_OPERATION,
            authority=DRC_AUTHORITY,
            comparison_method=DRC_COMPARISON_METHOD,
            native_result_hash=None,
            custom_result_hash=None,
            authority_available=False,
            reason="Native KiCad DRC authority step did not complete successfully.",
        )
    if not report_path.is_file():
        return classify_differential_result(
            source_sha=source_sha,
            lane=lane,
            kicad_version=kicad_version,
            fixture_id=fixture_id,
            fixture_hash=fixture_hash,
            operation=DRC_OPERATION,
            authority=DRC_AUTHORITY,
            comparison_method=DRC_COMPARISON_METHOD,
            native_result_hash=None,
            custom_result_hash=None,
            authority_available=False,
            reason=f"Native KiCad DRC report was not produced: {report_path.name}",
        )

    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return classify_differential_result(
            source_sha=source_sha,
            lane=lane,
            kicad_version=kicad_version,
            fixture_id=fixture_id,
            fixture_hash=fixture_hash,
            operation=DRC_OPERATION,
            authority=DRC_AUTHORITY,
            comparison_method=DRC_COMPARISON_METHOD,
            native_result_hash=None,
            custom_result_hash=None,
            infrastructure_valid=False,
            reason=(
                f"Native KiCad DRC report is not valid JSON: line {exc.lineno}, column {exc.colno}."
            ),
        )
    except OSError as exc:
        return classify_differential_result(
            source_sha=source_sha,
            lane=lane,
            kicad_version=kicad_version,
            fixture_id=fixture_id,
            fixture_hash=fixture_hash,
            operation=DRC_OPERATION,
            authority=DRC_AUTHORITY,
            comparison_method=DRC_COMPARISON_METHOD,
            native_result_hash=None,
            custom_result_hash=None,
            infrastructure_valid=False,
            reason=f"Native KiCad DRC report could not be read: {exc}",
        )

    try:
        native_projection = _native_projection(report)
    except ValueError as exc:
        return classify_differential_result(
            source_sha=source_sha,
            lane=lane,
            kicad_version=kicad_version,
            fixture_id=fixture_id,
            fixture_hash=fixture_hash,
            operation=DRC_OPERATION,
            authority=DRC_AUTHORITY,
            comparison_method=DRC_COMPARISON_METHOD,
            native_result_hash=None,
            custom_result_hash=None,
            infrastructure_valid=False,
            reason=str(exc),
        )

    native_pass = native_projection[0] == "pass"
    try:
        custom_pass, custom_projection, custom_detail = _custom_projection(
            report, custom_classifier
        )
    except ValueError as exc:
        return classify_differential_result(
            source_sha=source_sha,
            lane=lane,
            kicad_version=kicad_version,
            fixture_id=fixture_id,
            fixture_hash=fixture_hash,
            operation=DRC_OPERATION,
            authority=DRC_AUTHORITY,
            comparison_method=DRC_COMPARISON_METHOD,
            native_result_hash=_sha256_projection(native_projection),
            custom_result_hash=None,
            native_pass=native_pass,
            infrastructure_valid=False,
            reason=f"MCP Pro DRC normalization failed: {exc}",
        )
    return classify_differential_result(
        source_sha=source_sha,
        lane=lane,
        kicad_version=kicad_version,
        fixture_id=fixture_id,
        fixture_hash=fixture_hash,
        operation=DRC_OPERATION,
        authority=DRC_AUTHORITY,
        comparison_method=DRC_COMPARISON_METHOD,
        native_result_hash=_sha256_projection(native_projection),
        custom_result_hash=_sha256_projection(custom_projection),
        native_pass=native_pass,
        custom_pass=custom_pass,
        reason=custom_detail,
    )


__all__ = [
    "DRC_AUTHORITY",
    "DRC_COMPARISON_METHOD",
    "DRC_OPERATION",
    "compare_drc_report_file",
    "hash_fixture_tree",
]

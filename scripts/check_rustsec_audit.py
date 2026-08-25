#!/usr/bin/env python3
"""Validate cargo-audit JSON against the reviewed RustSec dependency baseline."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast


class RustSecAuditError(ValueError):
    """Raised when RustSec audit evidence is invalid or differs from baseline."""


@dataclass(frozen=True, order=True)
class Finding:
    advisory_id: str
    package: str
    version: str
    category: str

    def render(self) -> str:
        return f"{self.advisory_id}:{self.package}@{self.version}:{self.category}"


def _object(value: object, description: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RustSecAuditError(f"{description} must be a JSON object")
    return cast(dict[str, Any], value)


def _load_object(path: Path, description: str) -> dict[str, Any]:
    try:
        return _object(json.loads(path.read_text(encoding="utf-8")), description)
    except (OSError, json.JSONDecodeError) as exc:
        raise RustSecAuditError(f"{description} is unreadable or invalid JSON") from exc


def _finding(value: object, category: str) -> Finding:
    item = _object(value, f"cargo-audit {category} finding")
    advisory = _object(item.get("advisory"), f"cargo-audit {category} advisory")
    package = _object(item.get("package"), f"cargo-audit {category} package")
    advisory_id = advisory.get("id")
    package_name = package.get("name")
    version = package.get("version")
    if not isinstance(advisory_id, str) or not advisory_id:
        raise RustSecAuditError(f"cargo-audit {category} advisory id is incomplete")
    if not isinstance(package_name, str) or not package_name:
        raise RustSecAuditError(f"cargo-audit {category} package name is incomplete")
    if not isinstance(version, str) or not version:
        raise RustSecAuditError(f"cargo-audit {category} package version is incomplete")
    return Finding(advisory_id, package_name, version, category)


def _report_findings(report: dict[str, Any]) -> set[Finding]:
    findings: set[Finding] = set()
    vulnerabilities = _object(report.get("vulnerabilities", {}), "cargo-audit vulnerabilities")
    vulnerable = vulnerabilities.get("list", [])
    if not isinstance(vulnerable, list):
        raise RustSecAuditError("cargo-audit vulnerabilities.list must be an array")
    findings.update(_finding(item, "vulnerability") for item in vulnerable)

    warnings = _object(report.get("warnings", {}), "cargo-audit warnings")
    for category, items in warnings.items():
        if not isinstance(items, list):
            raise RustSecAuditError(f"cargo-audit warning category {category} must be an array")
        findings.update(_finding(item, str(category)) for item in items)
    return findings


def _baseline_findings(baseline: dict[str, Any], cargo_audit_version: str) -> set[Finding]:
    if baseline.get("schema_version") != 1:
        raise RustSecAuditError("RustSec baseline schema_version must be 1")
    expected_tool = baseline.get("cargo_audit_version")
    if expected_tool != cargo_audit_version:
        raise RustSecAuditError(
            f"cargo-audit version mismatch: baseline={expected_tool!r} "
            f"actual={cargo_audit_version!r}"
        )
    advisories = baseline.get("advisories")
    if not isinstance(advisories, list):
        raise RustSecAuditError("RustSec baseline advisories must be an array")

    findings: set[Finding] = set()
    for entry in advisories:
        item = _object(entry, "RustSec baseline entry")
        required_identity = (
            item.get("id"),
            item.get("package"),
            item.get("version"),
            item.get("category"),
        )
        if not all(isinstance(field, str) and field for field in required_identity):
            raise RustSecAuditError("RustSec baseline finding identity is incomplete")
        if not all(
            isinstance(item.get(field), str) and item[field].strip()
            for field in ("rationale", "revisit", "source")
        ):
            raise RustSecAuditError("RustSec baseline review metadata is incomplete")
        expected_source = f"https://rustsec.org/advisories/{item['id']}"
        if item["source"] != expected_source:
            raise RustSecAuditError(f"RustSec baseline source must be {expected_source}")
        finding = Finding(*cast(tuple[str, str, str, str], required_identity))
        if finding in findings:
            raise RustSecAuditError(f"duplicate RustSec baseline entry: {finding.render()}")
        findings.add(finding)
    return findings


def validate_report(*, report_path: Path, baseline_path: Path, cargo_audit_version: str) -> None:
    """Fail unless cargo-audit findings match the exact reviewed baseline."""
    actual = _report_findings(_load_object(report_path, "cargo-audit report"))
    expected = _baseline_findings(
        _load_object(baseline_path, "RustSec baseline"), cargo_audit_version
    )
    unexpected = sorted(actual - expected)
    stale = sorted(expected - actual)
    messages: list[str] = []
    if unexpected:
        messages.append(
            "unexpected RustSec findings: " + ", ".join(item.render() for item in unexpected)
        )
    if stale:
        messages.append(
            "stale RustSec baseline entries: " + ", ".join(item.render() for item in stale)
        )
    if messages:
        raise RustSecAuditError("; ".join(messages))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--cargo-audit-version", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        validate_report(
            report_path=args.report,
            baseline_path=args.baseline,
            cargo_audit_version=args.cargo_audit_version,
        )
    except RustSecAuditError as exc:
        print(f"RustSec audit baseline check failed: {exc}", file=sys.stderr)
        return 1
    print("RustSec audit findings match the reviewed baseline.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

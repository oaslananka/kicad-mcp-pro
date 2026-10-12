#!/usr/bin/env python3
"""Structural review of a native-agent MCP smoke report, not attestation.

No client is launched and no untrusted transcript is displayed. Only a human
reviewing external native-host execution evidence may approve a host claim.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from scripts.check_agent_host_evidence import EVIDENCE

SCHEMA = "native-agent-host-smoke.v1"
_FIELDS = frozenset(
    {
        "schema_version",
        "host_id",
        "host_version",
        "os",
        "source_revision",
        "server_version",
        "transport",
        "mode",
        "mcp_server_discovered",
        "skills_discovered",
        "tool_called",
        "tool_call_successful",
        "write_tools_absent",
        "observed_on",
        "sanitized_log_sha256",
    }
)
_ALLOWED_SKILLS = frozenset(
    {
        "drc-check",
        "fabrication-output",
        "kicad-design-review",
        "pcb-design",
        "schematic-review",
        "visual-excellence",
        "wired-subcircuit-design",
    }
)
_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}\Z")
_VERSION = re.compile(r"\d[A-Za-z0-9.+-]{0,79}\Z", re.ASCII)
_DATE = re.compile(r"20\d{2}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])\Z", re.ASCII)
_SHA = re.compile(r"[0-9a-f]{40}\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")


def _valid_text(value: object, regex: re.Pattern[str]) -> bool:
    return type(value) is str and bool(regex.fullmatch(value))


def _validate_host_identity(
    report: dict[str, object], known_hosts: set[str], errors: set[str]
) -> None:
    if report["schema_version"] != SCHEMA:
        errors.add("invalid_schema_version")
    if not _valid_text(report["host_id"], _TOKEN) or report["host_id"] not in known_hosts:
        errors.add("unknown_host")
    for field in ("host_version", "server_version"):
        if not _valid_text(report[field], _VERSION):
            errors.add("invalid_version")
    if report["os"] not in ("linux", "windows", "macos"):
        errors.add("invalid_platform")
    if not _valid_text(report["source_revision"], _SHA):
        errors.add("invalid_source_revision")
    if not _valid_text(report["sanitized_log_sha256"], _DIGEST):
        errors.add("missing_sanitized_log_digest")
    if not _valid_text(report["observed_on"], _DATE):
        errors.add("invalid_observation_date")


def _validate_readonly_observations(report: dict[str, object], errors: set[str]) -> None:
    if report["transport"] not in ("stdio", "streamable-http") or report["mode"] != "readonly":
        errors.add("unsafe_transport_or_mode")
    for field in ("mcp_server_discovered", "tool_call_successful", "write_tools_absent"):
        if type(report[field]) is not bool or not report[field]:
            errors.add("missing_readonly_smoke_observation")
    if report["tool_called"] not in ("kicad_get_server_info", "kicad_get_version"):
        errors.add("invalid_readonly_tool")
    skills = report["skills_discovered"]
    if (
        not isinstance(skills, list)
        or not skills
        or any(not isinstance(item, str) or item not in _ALLOWED_SKILLS for item in skills)
        or len(set(skills)) != len(skills)
    ):
        errors.add("invalid_skill_discovery")


def validate_report(report: object, *, known_hosts: set[str]) -> list[str]:
    """Return constant safe error codes; never echo user-supplied text."""
    errors: set[str] = set()
    if not isinstance(report, dict) or set(report) != _FIELDS:
        return ["invalid_schema_fields"]
    _validate_host_identity(report, known_hosts, errors)
    _validate_readonly_observations(report, errors)
    return sorted(errors)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, default=EVIDENCE)
    args = parser.parse_args(argv)
    try:
        if (
            args.report.is_symlink()
            or not args.report.is_file()
            or args.report.stat().st_size > 16_384
        ):
            raise ValueError("invalid")
        catalog = json.loads(args.catalog.read_text(encoding="utf-8"))
        known = {row["id"] for row in catalog["hosts"]}
        errors = validate_report(
            json.loads(args.report.read_text(encoding="utf-8")), known_hosts=known
        )
    except (OSError, ValueError, TypeError, KeyError):
        errors = ["invalid_or_missing_evidence"]
    print(
        json.dumps(
            {
                "schema_version": "agent-host-smoke-structure-review.v1",
                "status": "structurally_complete_not_attested" if not errors else "rejected",
                "reason_codes": errors,
                "establishes_real_host_compatibility": False,
            },
            sort_keys=True,
        )
    )
    return 0 if not errors else 2


if __name__ == "__main__":
    sys.exit(main())

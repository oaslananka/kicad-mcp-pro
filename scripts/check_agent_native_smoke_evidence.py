#!/usr/bin/env python3
"""Structural review of a native-agent MCP smoke report, not attestation.

No client is launched and no untrusted transcript is displayed. Only a human
reviewing external native-host execution evidence may approve a host claim.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
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


# Reviewed source capability+operating-mode snapshots. The registry and
# tool_required_mode implementations are unchanged between these two source
# revisions. Explicitly opt in new revisions only after independent review;
# never trust the sanitized log's own readonly=True assertion.
_PINNED_SOURCE_REVISIONS = frozenset(
    {
        "57c0efb1f072f5fffbf1f527ee2348448705e32d",
        "f9a21b4e7fad0267bc162b864faea7be1081acbe",
    }
)
_PINNED_SOURCE_READONLY_TOOLS = frozenset(
    {
        "dfm_run_manufacturer_check",
        "kicad_get_project_info",
        "kicad_get_server_info",
        "kicad_get_tools_in_category",
        "kicad_get_version",
        "kicad_list_tool_categories",
        "kicad_set_project",
        "lib_get_bom_with_pricing",
        "lib_verify_component_contract",
        "pcb_get_board_summary",
        "pcb_get_design_rules",
        "pcb_get_stackup",
        "pcb_visual_qa",
        "project_design_workflow",
        "project_get_next_action",
        "project_quality_gate",
        "run_drc",
        "run_erc",
        "sch_get_bounding_boxes",
        "sch_get_connectivity_graph",
        "sch_get_symbols",
        "sch_visual_qa",
        "validate_design",
        "validate_footprints_vs_schematic",
    }
)


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


def _check_log_identity(report: dict[str, object], log: dict[str, object]) -> str | None:
    if report.get("host_id") != "codex" or log.get("host_id") != "codex":
        return "unsupported_log_host"
    linked = (
        ("host_version", "host_version"),
        ("os", "os"),
        ("source_revision", "source_revision"),
        ("server_version", "server_version"),
        ("transport", "transport"),
        ("mode", "mode"),
        ("observed_on", "observed_on"),
        ("tool_called", "native_tool_called"),
        ("tool_call_successful", "native_tool_call_successful"),
        ("mcp_server_discovered", "host_initialized"),
        ("write_tools_absent", "all_native_exposed_tools_readonly_per_source_policy"),
    )
    if any(log.get(log_key) != report.get(report_key) for report_key, log_key in linked):
        return "sanitized_log_report_mismatch"
    for key in (
        "source_module_loaded_from_exact_checkout",
        "host_initialized",
        "ephemeral_thread_created",
        "native_tool_call_successful",
        "native_tool_call_content_present",
        "all_native_exposed_tools_readonly_per_source_policy",
        "explicit_unbound_ipc_configured",
    ):
        if log.get(key) is not True:
            return "unsafe_or_incomplete_native_observation"
    for key in (
        "ipc_socket_materialized",
        "model_or_agent_turn_started",
        "raw_tool_response_retained",
        "full_native_host_smoke_independently_attested",
    ):
        if log.get(key) is not False:
            return "unsafe_or_incomplete_native_observation"
    if log.get("native_tool_call_method") != "mcpServer/tool/call":
        return "invalid_native_call_method"
    for key in ("host_binary_sha256", "python_binary_sha256"):
        if not _valid_text(log.get(key), _DIGEST):
            return "missing_reviewed_binary_digest"
    return None


def _check_log_inventory(report: dict[str, object], log: dict[str, object]) -> str | None:
    skills = log.get("project_skills_verified")
    if (
        not isinstance(skills, dict)
        or set(skills) != set(report.get("skills_discovered", []))
        or any(
            type(name) is not str or path != f".agents/skills/{name}/SKILL.md"
            for name, path in skills.items()
        )
    ):
        return "invalid_sanitized_skill_origins"
    names = log.get("native_host_tool_names")
    if (
        not isinstance(names, list)
        or not names
        or not all(_valid_text(name, _TOKEN) for name in names)
        or len(names) != len(set(names))
        or type(log.get("native_tool_count")) is not int
        or len(names) != log["native_tool_count"]
        or report.get("tool_called") not in names
    ):
        return "invalid_sanitized_tool_inventory"
    if report.get("source_revision") not in _PINNED_SOURCE_REVISIONS:
        return "unreviewed_source_capability_policy"
    if set(names) != _PINNED_SOURCE_READONLY_TOOLS:
        return "invalid_sanitized_tool_policy"
    # Windows Codex 0.144.4 does not provide runtimeStatus; later versions
    # and Linux must prove an actual connected status, not just inventory.
    if log.get("os") == "windows" and log.get("host_version") == "0.144.4":
        if (
            log.get("native_inventory_server_info_present") is not True
            or log.get("native_mcp_status_field_available") is not False
            or "server_status" in log
        ):
            return "missing_native_server_inventory"
    elif (
        log.get("server_status") != "connected"
        or log.get("native_mcp_status_field_available") is False
    ):
        return "missing_native_server_connection"
    return None


def _check_log_redaction(log: dict[str, object]) -> str | None:
    # Use decoded JSON scalars: paths can be escaped in the original bytes.
    forbidden = (
        "/home/",
        "/users/",
        "c:\\users\\",
        "sk-proj-",
        "authorization:",
        "access_token",
        "api_key",
    )
    stack: list[object] = [log]
    while stack:
        value = stack.pop()
        if isinstance(value, dict):
            stack.extend(value.keys())
            stack.extend(value.values())
        elif isinstance(value, list):
            stack.extend(value)
        elif isinstance(value, str):
            if any(item in value.lower() for item in forbidden):
                return "unsanitized_native_log"
    return None


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """Fail closed on duplicate keys, including in nested JSON objects."""
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate evidence JSON key")
        result[key] = value
    return result


def validate_sanitized_log(report: object, raw_log: bytes) -> list[str]:
    """Bind a Codex sanitized log to its report without trusting its assertions.

    This is deterministic evidence-consistency checking, NOT independent
    observation, binary provenance or compatibility attestation. Error output
    remains fixed codes; never echo untrusted log contents.
    """
    if not isinstance(report, dict) or len(raw_log) > 32_768 or not raw_log:
        return ["invalid_or_missing_log"]
    if hashlib.sha256(raw_log).hexdigest() != report.get("sanitized_log_sha256"):
        return ["sanitized_log_digest_mismatch"]
    try:
        log = json.loads(raw_log, object_pairs_hook=_unique_json_object)
    except (ValueError, RecursionError):
        return ["invalid_sanitized_log"]
    if (
        not isinstance(log, dict)
        or log.get("schema_version") != "codex-native-host-sanitized-log.v1"
    ):
        return ["invalid_sanitized_log"]
    reason = _check_log_identity(report, log)
    if reason is not None:
        return [reason]
    reason = _check_log_inventory(report, log)
    if reason is not None:
        return [reason]
    reason = _check_log_redaction(log)
    if reason is not None:
        return [reason]
    return []


def _read_bounded_regular_file(path: Path, limit: int) -> bytes:
    """Read evidence from one descriptor, never through a symlink or past limit.

    O_NOFOLLOW enforces this on supported systems. On Windows, keep the
    symlink/junction checks and require the opened file identity to match
    the preflight lstat. In all cases bound the read even if size changes.
    """
    if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
        raise ValueError("evidence link rejected")
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or before.st_size > limit:
        raise ValueError("invalid evidence file")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    fd = os.open(path, flags)
    try:
        opened = os.fstat(fd)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_size > limit
            or (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino)
        ):
            raise ValueError("changed or oversized evidence")
        with os.fdopen(fd, "rb") as stream:
            fd = -1
            raw = stream.read(limit + 1)
        if len(raw) > limit:
            raise ValueError("evidence exceeded bounded read")
        return raw
    finally:
        if fd >= 0:
            os.close(fd)


def _companion_sanitized_log_path(report: Path) -> Path | None:
    """Derive a fixed sibling filename; do not accept a second caller path."""
    match = re.fullmatch(
        r"(20\d{2}-\d{2}-\d{2}-(?:linux|windows|macos)-codex-native)-smoke[.]json",
        report.name,
        flags=re.ASCII,
    )
    if match is not None:
        return report.with_name(f"{match.group(1)}-sanitized-log.json")
    if report.name == "codex-native-smoke.json":
        return report.with_name("codex-native-sanitized-log.json")
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument(
        "--verify-sanitized-log",
        action="store_true",
        help="Validate the matching date/host log beside the selected report",
    )
    parser.add_argument("--catalog", type=Path, default=EVIDENCE)
    args = parser.parse_args(argv)
    try:
        catalog = json.loads(args.catalog.read_text(encoding="utf-8"))
        known = {row["id"] for row in catalog["hosts"]}
        report = json.loads(_read_bounded_regular_file(args.report, 16_384))
        errors = validate_report(report, known_hosts=known)
        if args.verify_sanitized_log and not errors:
            log_path = _companion_sanitized_log_path(args.report)
            if log_path is None:
                errors = ["invalid_or_missing_log"]
            else:
                try:
                    raw_log = _read_bounded_regular_file(log_path, 32_768)
                except (OSError, ValueError):
                    errors = ["invalid_or_missing_log"]
                else:
                    errors = validate_sanitized_log(report, raw_log)
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

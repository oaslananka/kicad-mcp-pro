"""Constrain dated Codex native observation to reviewed, sanitized facts."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts.check_agent_native_smoke_evidence import validate_report

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / "docs/evidence/agent-host"
REPORT = EVIDENCE / "2026-10-26-linux-codex-native-smoke.json"
LOG = EVIDENCE / "2026-10-26-linux-codex-native-sanitized-log.json"
CATALOG = ROOT / "integrations/common/agent-host-evidence.json"
PROJECT_SKILLS = {
    "drc-check",
    "fabrication-output",
    "kicad-design-review",
    "pcb-design",
    "schematic-review",
    "visual-excellence",
    "wired-subcircuit-design",
}


def _read_report() -> dict[str, object]:
    return json.loads(REPORT.read_text(encoding="utf-8"))


def _read_log() -> dict[str, object]:
    return json.loads(LOG.read_text(encoding="utf-8"))


def test_strict_structural_gate_accepts_observation_but_not_attestation() -> None:
    report = _read_report()
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    hosts = {item["id"] for item in catalog["hosts"]}

    assert validate_report(report, known_hosts=hosts) == []
    assert report["schema_version"] == "native-agent-host-smoke.v1"
    assert report["host_id"] == "codex"
    assert report["host_version"] == "0.163.0"
    assert report["source_revision"] == "57c0efb1f072f5fffbf1f527ee2348448705e32d"
    assert report["tool_called"] == "kicad_get_server_info"
    assert sorted(report["skills_discovered"]) == sorted(PROJECT_SKILLS)
    assert report["write_tools_absent"] is True
    assert report["tool_call_successful"] is True

    assert catalog["evidenceScope"] == "repository-static"
    assert all(item["smokeStatus"] == "not-run" for item in catalog["hosts"])


def test_sanitized_native_log_digest_and_source_scope() -> None:
    report, log = _read_report(), _read_log()
    raw = LOG.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == report["sanitized_log_sha256"]
    assert log["source_revision"] == report["source_revision"]
    assert log["source_module_loaded_from_exact_checkout"] is True
    assert log["server_status"] == "connected"
    assert log["mode"] == "readonly"
    assert log["profile"] == "default"
    assert log["native_tool_count"] == 24
    assert len(log["native_host_tool_names"]) == log["native_tool_count"]
    assert len(set(log["native_host_tool_names"])) == log["native_tool_count"]
    assert log["all_native_exposed_tools_readonly_per_source_policy"] is True
    assert log["native_tool_called"] in log["native_host_tool_names"]
    assert log["native_tool_call_method"] == "mcpServer/tool/call"
    assert log["native_tool_call_successful"] is True
    assert log["native_tool_call_content_present"] is True

    skills = log["project_skills_verified"]
    assert set(skills) == PROJECT_SKILLS
    for name, relative in skills.items():
        assert relative == f".agents/skills/{name}/SKILL.md"
        assert (ROOT / relative).is_file()


def test_no_secrets_or_false_independent_compatibility_claims() -> None:
    report, log = _read_report(), _read_log()
    assert log["model_or_agent_turn_started"] is False
    assert log["raw_tool_response_retained"] is False
    assert log["full_native_host_smoke_independently_attested"] is False
    assert log["explicit_unbound_ipc_configured"] is True
    assert log["ipc_socket_materialized"] is False

    content = REPORT.read_text(encoding="utf-8") + LOG.read_text(encoding="utf-8")
    for forbidden in ("/home/", "/Users/", "api_key", "access_token", "Bearer ", "password"):
        assert forbidden not in content
    assert "source_revision" in content
    assert report["sanitized_log_sha256"] not in LOG.read_text(encoding="utf-8")

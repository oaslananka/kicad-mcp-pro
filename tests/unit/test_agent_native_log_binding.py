"""Offline report/log binding guards for bounded native Codex observations."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts.check_agent_native_smoke_evidence import main, validate_sanitized_log

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / "docs/evidence/agent-host"


def observation(platform: str) -> tuple[dict[str, object], bytes]:
    stem = f"2026-10-26-{platform}-codex-native"
    report = json.loads((EVIDENCE / f"{stem}-smoke.json").read_text(encoding="utf-8"))
    log = (EVIDENCE / f"{stem}-sanitized-log.json").read_bytes()
    return report, log


def altered(
    report: dict[str, object], raw: bytes, changes: dict[str, object]
) -> tuple[dict[str, object], bytes]:
    log = json.loads(raw)
    log.update(changes)
    new_raw = (json.dumps(log, indent=2, sort_keys=True) + "\n").encode()
    next_report = dict(report, sanitized_log_sha256=hashlib.sha256(new_raw).hexdigest())
    return next_report, new_raw


@pytest.mark.parametrize("platform", ["linux", "windows"])
def test_existing_observations_have_sha_bound_sanitized_logs(platform: str) -> None:
    report, raw = observation(platform)
    assert validate_sanitized_log(report, raw) == []
    assert report["sanitized_log_sha256"] == hashlib.sha256(raw).hexdigest()


@pytest.mark.parametrize("platform", ["linux", "windows"])
def test_cli_reports_structure_without_claiming_attestation(
    platform: str, capsys: pytest.CaptureFixture[str]
) -> None:
    stem = f"2026-10-26-{platform}-codex-native"
    assert (
        main(
            [
                "--report",
                str(EVIDENCE / f"{stem}-smoke.json"),
                "--sanitized-log",
                str(EVIDENCE / f"{stem}-sanitized-log.json"),
            ]
        )
        == 0
    )
    result = json.loads(capsys.readouterr().out)
    assert result == {
        "schema_version": "agent-host-smoke-structure-review.v1",
        "status": "structurally_complete_not_attested",
        "reason_codes": [],
        "establishes_real_host_compatibility": False,
    }


def test_log_binding_refuses_tampering_without_digest_update() -> None:
    report, raw = observation("linux")
    assert validate_sanitized_log(report, raw.replace(b"readonly", b"readwrite", 1)) == [
        "sanitized_log_digest_mismatch"
    ]


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"source_revision": "a" * 40}, "sanitized_log_report_mismatch"),
        ({"host_version": "0.0.0"}, "sanitized_log_report_mismatch"),
        ({"native_tool_call_successful": False}, "sanitized_log_report_mismatch"),
        ({"native_tool_call_method": "sdk/direct"}, "invalid_native_call_method"),
        (
            {"full_native_host_smoke_independently_attested": True},
            "unsafe_or_incomplete_native_observation",
        ),
        ({"raw_tool_response_retained": True}, "unsafe_or_incomplete_native_observation"),
        (
            {"source_module_loaded_from_exact_checkout": False},
            "unsafe_or_incomplete_native_observation",
        ),
        ({"host_binary_sha256": "unknown"}, "missing_reviewed_binary_digest"),
        (
            {"project_skills_verified": {"pcb-design": "../private/SKILL.md"}},
            "invalid_sanitized_skill_origins",
        ),
        (
            {"native_host_tool_names": ["kicad_get_server_info", "kicad_get_server_info"]},
            "invalid_sanitized_tool_inventory",
        ),
        ({"server_status": "disconnected"}, "missing_native_server_connection"),
        ({"injected": "C:\\Users\\personal"}, "unsanitized_native_log"),
    ],
)
def test_recomputed_digest_does_not_hide_unsafe_or_mismatched_log(
    changes: dict[str, object], reason: str
) -> None:
    report, raw = observation("linux")
    next_report, new_raw = altered(report, raw, changes)
    assert validate_sanitized_log(next_report, new_raw) == [reason]


def test_windows_observation_does_not_require_new_linux_status_field() -> None:
    report, raw = observation("windows")
    log = json.loads(raw)
    assert "runtimeStatus" not in log and "server_status" not in log
    assert log["native_mcp_status_field_available"] is False
    assert validate_sanitized_log(report, raw) == []
    changed_report, changed_raw = altered(
        report, raw, {"native_inventory_server_info_present": False}
    )
    assert validate_sanitized_log(changed_report, changed_raw) == [
        "missing_native_server_inventory"
    ]


def test_cli_rejects_missing_log_when_explicitly_requested(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    assert (
        main(
            [
                "--report",
                str(EVIDENCE / "2026-10-26-windows-codex-native-smoke.json"),
                "--sanitized-log",
                str(tmp_path / "missing.json"),
            ]
        )
        == 2
    )
    result = json.loads(capsys.readouterr().out)
    assert result["reason_codes"] == ["invalid_or_missing_log"]
    assert result["establishes_real_host_compatibility"] is False

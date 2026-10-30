"""Offline report/log binding guards for bounded native Codex observations."""

from __future__ import annotations

import base64
import hashlib
import io
import json
import sys
from pathlib import Path

import pytest

from scripts.check_agent_native_smoke_evidence import (
    _companion_sanitized_log_path,
    _read_bounded_regular_file,
    main,
    validate_sanitized_log,
)

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / "docs/evidence/agent-host"


def run_stdin(
    monkeypatch: pytest.MonkeyPatch,
    report_bytes: bytes,
    log_bytes: bytes = b"",
    *,
    name: str = "codex-native-smoke.json",
    verify_log: bool = False,
) -> int:
    payload = {
        "name": name,
        "report_b64": base64.b64encode(report_bytes).decode("ascii"),
        "log_b64": base64.b64encode(log_bytes).decode("ascii"),
    }
    monkeypatch.setattr(
        sys,
        "stdin",
        io.TextIOWrapper(io.BytesIO(json.dumps(payload).encode()), encoding="utf-8"),
    )
    args = ["--report", "-"]
    if verify_log:
        args.append("--verify-sanitized-log")
    return main(args)


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


def test_published_v450_codex_observation_is_bound_but_not_attested(
    capsys: pytest.CaptureFixture[str],
) -> None:
    report_path = EVIDENCE / "2026-10-31-linux-codex-native-smoke.json"
    log_path = EVIDENCE / "2026-10-31-linux-codex-native-sanitized-log.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    raw = log_path.read_bytes()
    log = json.loads(raw)

    assert report["source_revision"] == "9aa519b1bb82b3907eefedbba26285cf4431d856"
    assert report["server_version"] == "4.5.0"
    assert report["observed_on"] == "2026-10-31"
    assert hashlib.sha256(raw).hexdigest() == report["sanitized_log_sha256"]
    assert log["native_tool_count"] == 24
    assert log["model_or_agent_turn_started"] is False
    assert log["full_native_host_smoke_independently_attested"] is False
    assert validate_sanitized_log(report, raw) == []

    assert main(["--report", str(report_path), "--verify-sanitized-log"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "structurally_complete_not_attested"
    assert result["establishes_real_host_compatibility"] is False

    # A recomputed digest cannot silently approve an unreviewed source.
    unknown, tampered = altered(report, raw, {"source_revision": "a" * 40})
    unknown["source_revision"] = "a" * 40
    assert validate_sanitized_log(unknown, tampered) == ["unreviewed_source_capability_policy"]


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
                "--verify-sanitized-log",
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


@pytest.mark.parametrize("platform", ["linux", "windows"])
def test_undated_native_probe_pair_is_accepted(
    platform: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    report, log = observation(platform)
    assert run_stdin(monkeypatch, json.dumps(report).encode(), log, verify_log=True) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "structurally_complete_not_attested"
    assert output["establishes_real_host_compatibility"] is False


@pytest.mark.parametrize("nested", [False, True])
def test_duplicate_json_keys_fail_even_with_recomputed_digest(nested: bool) -> None:
    report, raw = observation("linux")
    duplicate = (
        b'"notes": {"note": "Authorization: hidden", "note": "safe"},\n  '
        if nested
        else b'"note": "Authorization: hidden", "note": "safe",\n  '
    )
    modified = raw.replace(b'"host_id": "codex",', duplicate + b'"host_id": "codex",', 1)
    assert modified != raw
    report["sanitized_log_sha256"] = hashlib.sha256(modified).hexdigest()
    assert validate_sanitized_log(report, modified) == ["invalid_sanitized_log"]


@pytest.mark.parametrize("with_log", [False, True])
def test_cli_rejects_shadowed_report_source_fields(
    with_log: bool,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    report, raw_log = observation("linux")
    raw = json.dumps(report)
    duplicated = raw.replace(
        '"source_revision": ',
        '"source_revision": "0000000000000000000000000000000000000000", "source_revision": ',
        1,
    )
    assert duplicated != raw
    assert (
        run_stdin(
            monkeypatch,
            duplicated.encode(),
            raw_log if with_log else b"",
            verify_log=with_log,
        )
        == 2
    )
    result = json.loads(capsys.readouterr().out)
    assert result["reason_codes"] == ["invalid_or_missing_evidence"]
    assert result["establishes_real_host_compatibility"] is False


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
    assert "runtimeStatus" not in log
    assert "server_status" not in log
    assert log["native_mcp_status_field_available"] is False
    assert validate_sanitized_log(report, raw) == []
    changed_report, changed_raw = altered(
        report, raw, {"native_inventory_server_info_present": False}
    )
    assert validate_sanitized_log(changed_report, changed_raw) == [
        "missing_native_server_inventory"
    ]


def test_cli_rejects_missing_log_when_explicitly_requested(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    report, _ = observation("windows")
    assert run_stdin(monkeypatch, json.dumps(report).encode(), verify_log=True) == 2
    result = json.loads(capsys.readouterr().out)
    assert result["reason_codes"] == ["invalid_or_missing_evidence"]
    assert result["establishes_real_host_compatibility"] is False


def test_bounded_reader_accepts_exact_limit_without_extra_bytes(tmp_path: Path) -> None:
    file = tmp_path / "evidence.json"
    file.write_bytes(b"x" * 1024)
    assert _read_bounded_regular_file(file, 1024) == b"x" * 1024
    with pytest.raises(ValueError, match="evidence"):
        _read_bounded_regular_file(file, 1023)


def test_bounded_reader_rejects_symlink_and_nonregular_file(tmp_path: Path) -> None:
    target = tmp_path / "real-log.json"
    target.write_bytes(b"{}")
    link = tmp_path / "linked-log.json"
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are unavailable to this platform account")
    with pytest.raises(ValueError, match="link"):
        _read_bounded_regular_file(link, 32_768)
    with pytest.raises(ValueError, match="invalid evidence"):
        _read_bounded_regular_file(tmp_path, 32_768)


def test_cli_rejects_oversized_log(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    report, _ = observation("linux")
    assert run_stdin(monkeypatch, json.dumps(report).encode(), b"x" * 32_769, verify_log=True) == 2
    result = json.loads(capsys.readouterr().out)
    assert result["reason_codes"] == ["invalid_or_missing_evidence"]


def test_companion_log_name_accepts_only_expected_basenames(tmp_path: Path) -> None:
    fields = {"observed_on": "2026-10-26", "os": "windows"}
    assert (
        _companion_sanitized_log_path(
            tmp_path / "2026-10-26-windows-codex-native-smoke.json", fields
        )
        == tmp_path / "2026-10-26-windows-codex-native-sanitized-log.json"
    )
    assert (
        _companion_sanitized_log_path(tmp_path / "codex-native-smoke.json", fields)
        == tmp_path / "codex-native-sanitized-log.json"
    )
    for name in (
        "report.json",
        "../private.json",
        "2026-١٠-26-windows-codex-native-smoke.json",
        "2026-10-26-windows-codex-native-smoke.json.bak",
        "2026-10-26-windows-codex-native-smoke.json/other",
    ):
        assert _companion_sanitized_log_path(tmp_path / name, fields) is None


def test_native_tool_policy_is_pinned_to_source_capabilities() -> None:
    from kicad_mcp.capabilities import get
    from kicad_mcp.operating_modes import OperatingMode, tool_required_mode
    from scripts.check_agent_native_smoke_evidence import _PINNED_SOURCE_READONLY_TOOLS

    for name in _PINNED_SOURCE_READONLY_TOOLS:
        assert get(name) is not None
        assert tool_required_mode(name) is OperatingMode.READONLY


def test_recomputed_hash_rejects_unknown_or_mutating_tool() -> None:
    report, raw = observation("linux")
    for tool in ("unknown_tool", "pcb_save"):
        log = json.loads(raw)
        log["native_host_tool_names"][0] = tool
        changed_raw = (json.dumps(log, sort_keys=True) + "\n").encode()
        updated = dict(report, sanitized_log_sha256=hashlib.sha256(changed_raw).hexdigest())
        assert validate_sanitized_log(updated, changed_raw) == ["invalid_sanitized_tool_policy"]


def test_recomputed_hash_rejects_unreviewed_source_revision() -> None:
    report, raw = observation("linux")
    updated, changed = altered(report, raw, {"source_revision": "a" * 40})
    updated["source_revision"] = "a" * 40
    assert validate_sanitized_log(updated, changed) == ["unreviewed_source_capability_policy"]


def test_newer_windows_host_must_prove_connected_status() -> None:
    report, raw = observation("windows")
    changed_report, changed = altered(report, raw, {"host_version": "0.163.0"})
    changed_report["host_version"] = "0.163.0"
    assert validate_sanitized_log(changed_report, changed) == ["missing_native_server_connection"]
    disconnected_report, disconnected = altered(
        changed_report, changed, {"server_status": "disconnected"}
    )
    assert validate_sanitized_log(disconnected_report, disconnected) == [
        "missing_native_server_connection"
    ]
    connected_report, connected = altered(
        disconnected_report,
        disconnected,
        {
            "server_status": "connected",
            "native_mcp_status_field_available": True,
        },
    )
    assert validate_sanitized_log(connected_report, connected) == []


def test_legacy_windows_host_rejects_spoofed_status() -> None:
    report, raw = observation("windows")
    changed_report, changed = altered(report, raw, {"server_status": "connected"})
    assert validate_sanitized_log(changed_report, changed) == ["missing_native_server_inventory"]


@pytest.mark.parametrize(
    ("name", "platform", "date"),
    [
        ("2026-10-26-windows-codex-native-smoke.json", "linux", "2026-10-26"),
        ("2026-10-27-linux-codex-native-smoke.json", "linux", "2026-10-26"),
    ],
)
def test_dated_archive_filename_must_match_report_fields(
    name: str,
    platform: str,
    date: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    report, log = observation("linux")
    assert report["os"] == platform
    assert report["observed_on"] == date
    assert run_stdin(monkeypatch, json.dumps(report).encode(), log, name=name, verify_log=True) == 2
    result = json.loads(capsys.readouterr().out)
    assert result["reason_codes"] == ["invalid_or_missing_evidence"]
    assert result["establishes_real_host_compatibility"] is False


def test_arbitrary_cli_path_rejected_without_opening(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    file = tmp_path / "codex-native-smoke.json"
    file.write_text('{"not": "a fixture"}', encoding="utf-8")
    assert main(["--report", str(file)]) == 2
    result = json.loads(capsys.readouterr().out)
    assert result["reason_codes"] == ["invalid_or_missing_evidence"]


@pytest.mark.parametrize(
    "name",
    ("../../secret.json", "custom.json", "2026-10-26-../codex-native-smoke.json"),
)
def test_stdin_evidence_name_rejects_traversal(
    name: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    report, log = observation("linux")
    assert run_stdin(monkeypatch, json.dumps(report).encode(), log, name=name, verify_log=True) == 2
    result = json.loads(capsys.readouterr().out)
    assert result["reason_codes"] == ["invalid_or_missing_evidence"]

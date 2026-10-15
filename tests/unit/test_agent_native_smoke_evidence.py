"""Host evidence structure must not become self-authorizing proof."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import check_agent_native_smoke_evidence as gate


def _sample() -> dict:
    return {
        "schema_version": gate.SCHEMA,
        "host_id": "codex",
        "host_version": "0.150.1",
        "os": "linux",
        "source_revision": "a" * 40,
        "server_version": "4.3.0",
        "transport": "stdio",
        "mode": "readonly",
        "mcp_server_discovered": True,
        "skills_discovered": ["pcb-design"],
        "tool_called": "kicad_get_version",
        "tool_call_successful": True,
        "write_tools_absent": True,
        "observed_on": "2026-10-11",
        "sanitized_log_sha256": "b" * 64,
    }


def test_synthetic_fixture_only_passes_structure_not_attestation() -> None:
    assert gate.validate_report(_sample(), known_hosts={"codex"}) == []
    assert gate.main  # actual approval is deliberately not a tool action


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        ({"host_id": "unverified"}, "unknown_host"),
        ({"host_version": "/Users/private/.config"}, "invalid_version"),
        ({"source_revision": "current"}, "invalid_source_revision"),
        ({"sanitized_log_sha256": ""}, "missing_sanitized_log_digest"),
        ({"mode": "write"}, "unsafe_transport_or_mode"),
        ({"transport": "sse"}, "unsafe_transport_or_mode"),
        ({"mcp_server_discovered": False}, "missing_readonly_smoke_observation"),
        ({"write_tools_absent": False}, "missing_readonly_smoke_observation"),
        ({"skills_discovered": []}, "invalid_skill_discovery"),
        ({"tool_called": "pcb_delete_items"}, "invalid_readonly_tool"),
        ({"observed_on": "now"}, "invalid_observation_date"),
    ],
)
def test_mutations_fail_closed(change: dict, expected: str) -> None:
    report = _sample() | change
    assert expected in gate.validate_report(report, known_hosts={"codex"})


def test_additional_transcript_is_rejected() -> None:
    report = _sample()
    report["raw_transcript"] = "private prompt"
    assert gate.validate_report(report, known_hosts={"codex"}) == ["invalid_schema_fields"]


def test_cli_does_not_echo_untrusted_data(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    f = tmp_path / "native-evidence.json"
    sample = _sample()
    sample["host_id"] = "/private/user-token"
    f.write_text(json.dumps(sample))
    assert gate.main(["--report", str(f)]) == 2
    output = capsys.readouterr().out
    assert "rejected" in output
    assert "/private" not in output
    assert "establishes_real_host_compatibility" in output


def test_cli_structure_only_is_not_verified(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    f = tmp_path / "native-evidence.json"
    f.write_text(json.dumps(_sample()))
    assert gate.main(["--report", str(f)]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "structurally_complete_not_attested"
    assert output["establishes_real_host_compatibility"] is False


def test_missing_or_symlinked_report_fails_closed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    f = tmp_path / "not-created"
    assert gate.main(["--report", str(f)]) == 2
    f.symlink_to(gate.EVIDENCE)
    assert gate.main(["--report", str(f)]) == 2
    output = capsys.readouterr().out
    assert output.count("rejected") == 2


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        ({"host_version": "١.2.3"}, "invalid_version"),
        ({"server_version": "٤.3.0"}, "invalid_version"),
        ({"observed_on": "20٢6-10-11"}, "invalid_observation_date"),
        ({"skills_discovered": ["pcb-design", "pcb-design"]}, "invalid_skill_discovery"),
        ({"skills_discovered": [{"untrusted": "pcb-design"}]}, "invalid_skill_discovery"),
    ],
)
def test_unicode_digits_and_untrusted_skills_fail_closed(change: dict, expected: str) -> None:
    report = _sample() | change
    assert expected in gate.validate_report(report, known_hosts={"codex"})

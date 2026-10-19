"""Fail-closed, zero-mutation preflight for the reviewed reference agent runner."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import check_reference_board_attempt_readiness as cli

ROOT = Path(__file__).resolve().parents[2]


def _safe_checks(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "discover_reference_source_revision", lambda _: "a" * 40)
    monkeypatch.setattr(cli, "_kicad_10_cli_available", lambda: True)
    monkeypatch.setattr(
        cli.shutil, "which", lambda name: "/trusted/claude" if name == "claude" else None
    )


def test_readiness_has_stable_reviewed_inputs_and_no_side_effects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _safe_checks(monkeypatch)
    result = cli.preflight(
        root=ROOT, board_id="esp32-c6-usbc", attempt_number=812, phase_name="schematic"
    )
    assert result["status"] == "ready", result
    assert result["executes_agent"] is False
    assert result["counts_as_task_success"] is False
    assert result["source_revision"] == "a" * 40
    assert result["agent"] == "claude"
    assert result["operating_mode"] == "write"
    assert set(result["reviewed_input_sha256"]) == set(cli._INPUTS)
    assert all(len(v) == 64 for v in result["reviewed_input_sha256"].values())
    assert "/home/" not in json.dumps(result)


def test_absent_host_and_source_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    _safe_checks(monkeypatch)
    monkeypatch.setattr(cli.shutil, "which", lambda _: None)
    monkeypatch.setattr(
        cli,
        "discover_reference_source_revision",
        lambda _: (_ for _ in ()).throw(cli.ReferenceAgentRunnerError("local private path")),
    )
    result = cli.preflight(root=ROOT, board_id="rp2350-usbc", attempt_number=913, phase_name="pcb")
    assert result["status"] == "blocked"
    assert "reviewed_agent_cli_unavailable" in result["blocking_reasons"]
    assert "source_revision_not_reproducible" in result["blocking_reasons"]
    assert "local private path" not in json.dumps(result)


def test_existing_attempt_directory_is_never_reused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _safe_checks(monkeypatch)
    base = tmp_path / "docs/evidence/reference-boards/esp32-c6-usbc/v1"
    base.mkdir(parents=True)
    for name in cli._INPUTS:
        (base / name).write_bytes(
            (ROOT / "docs/evidence/reference-boards/esp32-c6-usbc/v1" / name).read_bytes()
        )
    (base / "attempts/attempt-003").mkdir(parents=True)
    outcome = cli.preflight(
        root=tmp_path, board_id="esp32-c6-usbc", attempt_number=3, phase_name="pcb"
    )
    assert outcome["status"] == "blocked"
    assert "attempt_identity_already_used" in outcome["blocking_reasons"]


def test_bad_metadata_fails_closed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _safe_checks(monkeypatch)
    base = tmp_path / "docs/evidence/reference-boards/esp32-c6-usbc/v1"
    base.mkdir(parents=True)
    for name in cli._INPUTS:
        (base / name).write_bytes(
            (ROOT / "docs/evidence/reference-boards/esp32-c6-usbc/v1" / name).read_bytes()
        )
    payload = json.loads((base / "quality-gates.json").read_text())
    payload["board_id"] = "wrong-board"
    (base / "quality-gates.json").write_text(json.dumps(payload))
    outcome = cli.preflight(
        root=tmp_path, board_id="esp32-c6-usbc", attempt_number=10, phase_name="schematic"
    )
    assert "invalid_benchmark_metadata" in outcome["blocking_reasons"]


def test_missing_and_symlinked_inputs_are_rejected(tmp_path: Path) -> None:
    missing = tmp_path / "absent"
    with pytest.raises(ValueError, match="reviewed"):
        cli._input_sha256(missing)
    linked = tmp_path / "linked"
    linked.symlink_to(__file__)
    with pytest.raises(ValueError, match="reviewed"):
        cli._input_sha256(linked)


def test_actual_local_cli_reports_missing_agent_without_claiming_success(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code = cli.main(
        ["--board-id", "rp2350-usbc", "--attempt-number", "911", "--phase", "schematic"]
    )
    payload = json.loads(capsys.readouterr().out)
    assert code in (0, 2)
    assert payload["counts_as_task_success"] is False
    assert payload["executes_agent"] is False
    assert payload["status"] in ("ready", "blocked")


def test_kicad_cli_uses_existing_bounded_version_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli.shutil, "which", lambda _: "/reviewed/kicad-cli")
    monkeypatch.setattr(cli, "find_kicad_version", lambda _: "10.0.7")
    assert cli._kicad_10_cli_available() is True
    monkeypatch.setattr(cli, "find_kicad_version", lambda _: "11.0.0")
    assert cli._kicad_10_cli_available() is False
    monkeypatch.setattr(cli.shutil, "which", lambda _: None)
    assert cli._kicad_10_cli_available() is False


def _write_ops_server_config(
    tmp_path: Path,
    *,
    project: Path = ROOT,
    profile: str = "schematic_authoring",
    mode: str = "write",
) -> Path:
    executable = Path.home() / ".local/bin/uv"
    version = cli._pinned_uv_version(project)
    assert version is not None
    document = {
        "mcpServers": {
            "kicad-msi-schematic-review": {
                "type": "stdio",
                "command": str(executable),
                "args": [
                    "tool",
                    "run",
                    "--from",
                    f"uv=={version}",
                    "uv",
                    "run",
                    "--project",
                    str(project),
                    "--no-dev",
                    "python",
                    "-m",
                    "kicad_mcp.evals.reference_ops_server",
                    "--phase",
                    "schematic",
                ],
                "env": {
                    "KICAD_MCP_PROFILE": profile,
                    "KICAD_MCP_OPERATING_MODE": mode,
                },
                "enabled": True,
            }
        }
    }
    path = tmp_path / "mcp.json"
    path.write_text(json.dumps(document))
    path.chmod(0o600)
    return path


@pytest.mark.skipif(
    __import__("os").name == "nt",
    reason="The Ops preflight's POSIX owner-only file permission check is Linux-only",
)
def test_chatgpt_ops_preflight_is_an_explicit_nonexecuting_handoff(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _safe_checks(monkeypatch)
    config = _write_ops_server_config(tmp_path)
    outcome = cli.preflight(
        root=ROOT,
        board_id="stm32f072-usbc",
        attempt_number=812,
        phase_name="schematic",
        agent_runtime="chatgpt-ops",
        ops_server_name="kicad-msi-schematic-review",
        ops_config_path=config,
    )
    assert outcome["status"] == "handoff_required"
    assert outcome["agent"] == "chatgpt-ops"
    assert outcome["live_tool_attestation_required"] is True
    assert outcome["recorded_event_log_required"] is True
    assert outcome["executes_agent"] is False
    assert outcome["counts_as_task_success"] is False
    assert outcome["blocking_reasons"] == []
    assert "claude" not in json.dumps(outcome)
    assert str(config) not in json.dumps(outcome)


@pytest.mark.parametrize(
    "mutation",
    [
        "wrong-profile",
        "wrong-mode",
        "foreign-source",
        "active-socket",
        "insecure-permissions",
        "symlink",
        "missing",
        "disabled",
        "unreviewed-command",
        "unpinned-uv",
        "unreviewed-extra-flags",
    ],
)
def test_chatgpt_ops_preflight_rejects_unsafe_or_unpinned_servers(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, mutation: str
) -> None:
    _safe_checks(monkeypatch)
    config = _write_ops_server_config(tmp_path)
    data = json.loads(config.read_text())
    entry = data["mcpServers"]["kicad-msi-schematic-review"]
    if mutation == "wrong-profile":
        entry["env"]["KICAD_MCP_PROFILE"] = "build"
    elif mutation == "wrong-mode":
        entry["env"]["KICAD_MCP_OPERATING_MODE"] = "readonly"
    elif mutation == "foreign-source":
        entry["args"][entry["args"].index("--project") + 1] = str(tmp_path)
    elif mutation == "active-socket":
        entry["env"]["KICAD_API_SOCKET"] = "ipc:///tmp/kicad/api-existing.sock"
    elif mutation == "disabled":
        entry["enabled"] = False
    elif mutation == "unreviewed-command":
        entry["command"] = str(tmp_path / "mcp.json")
    elif mutation == "unpinned-uv":
        entry["args"][entry["args"].index("--from") + 1] = "uv==0.99.99"
    elif mutation == "unreviewed-extra-flags":
        entry["args"] += ["--allow-unsafe-tools"]
    if mutation in {
        "wrong-profile",
        "wrong-mode",
        "foreign-source",
        "active-socket",
        "disabled",
        "unreviewed-command",
        "unpinned-uv",
        "unreviewed-extra-flags",
    }:
        config.write_text(json.dumps(data))
    elif mutation == "insecure-permissions":
        config.chmod(0o644)
    elif mutation == "symlink":
        other = tmp_path / "target.json"
        config.rename(other)
        config.symlink_to(other)
    else:
        config.unlink()
    outcome = cli.preflight(
        root=ROOT,
        board_id="stm32f072-usbc",
        attempt_number=812,
        phase_name="schematic",
        agent_runtime="chatgpt-ops",
        ops_server_name="kicad-msi-schematic-review",
        ops_config_path=config,
    )
    assert outcome["status"] == "blocked"
    assert outcome["blocking_reasons"] == ["reviewed_ops_mcp_server_unavailable"]
    assert outcome["counts_as_task_success"] is False


def test_chatgpt_ops_manufacturing_remains_blocked_even_with_server(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _safe_checks(monkeypatch)
    config = _write_ops_server_config(tmp_path, profile="release", mode="manufacturing")
    outcome = cli.preflight(
        root=ROOT,
        board_id="stm32f072-usbc",
        attempt_number=812,
        phase_name="manufacturing",
        agent_runtime="chatgpt-ops",
        ops_server_name="kicad-msi-schematic-review",
        ops_config_path=config,
    )
    assert outcome["status"] == "blocked"
    assert "reviewed_ops_mcp_server_unavailable" in outcome["blocking_reasons"]

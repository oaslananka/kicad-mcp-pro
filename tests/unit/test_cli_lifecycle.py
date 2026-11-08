"""CLI lifecycle contract tests that never mutate installed tools."""

from __future__ import annotations

import json

from typer.testing import CliRunner

from kicad_mcp.cli_lifecycle import _install_manager, _manager_command
from kicad_mcp.cloud_user_cli import _local_pairing_storage_supported
from kicad_mcp.server import app


def test_windows_owner_key_storage_is_not_misreported_as_supported(monkeypatch) -> None:
    from types import SimpleNamespace

    from kicad_mcp import cloud_user_cli

    monkeypatch.setattr(cloud_user_cli, "os", SimpleNamespace(name="nt"))
    assert _local_pairing_storage_supported() is False


def test_package_manager_detection_only_accepts_known_tool_paths() -> None:
    assert (
        _install_manager("C:/Users/A/AppData/Roaming/uv/tools/kicad-mcp-pro/Scripts/python.exe")
        == "uv"
    )
    assert _install_manager("/home/a/.local/share/pipx/venvs/kicad-mcp-pro/bin/python") == "pipx"
    assert _install_manager("/usr/bin/python3") == "unknown"
    assert _manager_command("unknown", "uninstall") is None


def test_explicit_update_check_json_never_installs(monkeypatch) -> None:
    monkeypatch.setattr("kicad_mcp.cli_lifecycle._fetch_latest_stable", lambda: "99.0.0")
    monkeypatch.setattr("kicad_mcp.cli_lifecycle._install_manager", lambda: "uv")
    result = CliRunner().invoke(app, ["update", "check", "--json"])
    assert result.exit_code == 0, result.output
    report = json.loads(result.output)
    assert report["status"] == "update_available"
    assert report["upgrade_command"] == "uv tool upgrade kicad-mcp-pro"


def test_update_lookup_error_is_not_misreported_as_current(monkeypatch) -> None:
    from kicad_mcp.cli_lifecycle import ReleaseLookupError

    def offline() -> str:
        raise ReleaseLookupError("offline")

    monkeypatch.setattr("kicad_mcp.cli_lifecycle._fetch_latest_stable", offline)
    result = CliRunner().invoke(app, ["update", "check", "--json"])
    assert result.exit_code == 3
    assert json.loads(result.output)["status"] == "lookup_failed"


def test_uninstall_prints_command_without_touching_installed_files(monkeypatch) -> None:
    monkeypatch.setattr("kicad_mcp.cli_lifecycle._install_manager", lambda: "uv")
    result = CliRunner().invoke(app, ["uninstall"])
    assert result.exit_code == 0, result.output
    assert "uv tool uninstall kicad-mcp-pro" in result.output
    assert "No package, project or configuration was removed." in result.output


def test_setup_without_agent_is_safe_in_noninteractive_mode(monkeypatch) -> None:
    monkeypatch.setattr(
        "kicad_mcp.setup.run_wizard", lambda: (_ for _ in ()).throw(AssertionError("wizard"))
    )
    result = CliRunner().invoke(app, ["setup"])
    assert result.exit_code == 2
    assert "interactive terminal" in result.output


def test_setup_agent_option_is_an_alias_for_existing_positional(monkeypatch) -> None:
    monkeypatch.setattr(
        "kicad_mcp.setup.setup_agent",
        lambda agent, **_kw: f"configuration preview for {agent}",
    )
    result = CliRunner().invoke(app, ["setup", "--agent", "claude-code"])
    assert result.exit_code == 0, result.output
    assert "configuration preview for claude-code" in result.output


def test_setup_rejects_ambiguous_agent_selection() -> None:
    result = CliRunner().invoke(app, ["setup", "codex", "--agent", "claude-code"])
    assert result.exit_code != 0


def test_path_inventory_detects_multiple_launchers_without_executing_them(tmp_path) -> None:
    from kicad_mcp.cli_lifecycle import _path_launchers

    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    (first / "kicad-mcp-pro.exe").touch()
    (second / "kicad-mcp-pro.exe").touch()
    found = _path_launchers([str(first), str(second), str(first)], windows=True)
    assert len(found) == 2
    assert found[0].endswith("first\\kicad-mcp-pro.exe")


def test_doctor_warns_about_duplicate_launchers_without_running_them(monkeypatch) -> None:
    from kicad_mcp.diagnostics import _duplicate_cli_path_check

    monkeypatch.setattr(
        "kicad_mcp.cli_lifecycle._path_launchers",
        lambda: ["first/kicad-mcp-pro.exe", "second/kicad-mcp-pro.exe"],
    )
    check = _duplicate_cli_path_check()
    assert check is not None
    assert check.name == "cli_path_conflict"
    assert check.status == "warn"
    assert "Get-Command" in check.hint

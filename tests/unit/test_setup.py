"""Tests for kicad_mcp.setup module (Phase 2: installer/wizard/backup/restore)."""

from __future__ import annotations

import json
import sys
import tomllib
from pathlib import Path

import pytest
from typer.testing import CliRunner

from kicad_mcp.server import app
from kicad_mcp.setup import (
    AGENTS,
    _env_for_mode,
    _generate_codex_toml,
    _opencode_uses_v2,
    backup_config,
    check_agent_config,
    check_all_agent_configs,
    generate_config,
    resolve_path,
    setup_agent,
    validate_config,
    write_config,
)

# ---------------------------------------------------------------------------
# Agent metadata
# ---------------------------------------------------------------------------


class TestAgentMetadata:
    def test_all_agents_have_keys(self) -> None:
        assert "claude-code" in AGENTS
        assert "codex" in AGENTS
        assert "gemini" in AGENTS
        assert "opencode" in AGENTS
        assert "cursor" in AGENTS
        assert "vscode" in AGENTS
        assert "claude-desktop" in AGENTS
        assert "antigravity" in AGENTS
        assert "chatgpt" in AGENTS
        assert "claude-ai" in AGENTS

    def test_local_agents_have_scopes(self) -> None:
        for key, info in AGENTS.items():
            if info.kind == "local":
                assert len(info.supports_scope) > 0, f"{key} has no scopes"


# ---------------------------------------------------------------------------
# Resolve path
# ---------------------------------------------------------------------------


class TestResolvePath:
    def test_project_scope_returns_relative(self, tmp_path: Path) -> None:
        old_cwd = Path.cwd()
        try:
            __import__("os").chdir(tmp_path)
            path = resolve_path("claude-code", "project")
            assert str(path).endswith(".mcp.json")
        finally:
            __import__("os").chdir(str(old_cwd))

    def test_gemini_project_scope_resolves_local_settings(self, tmp_path: Path) -> None:
        path = resolve_path("gemini", "project", project_dir=tmp_path)
        assert path == tmp_path / ".gemini" / "settings.json"
        assert "user" in AGENTS["gemini"].supports_scope

    def test_gemini_project_setup_preserves_unrelated_settings(self, tmp_path: Path) -> None:
        settings = tmp_path / ".gemini" / "settings.json"
        settings.parent.mkdir(parents=True)
        settings.write_text(
            json.dumps(
                {
                    "theme": "dark",
                    "mcpServers": {"other": {"command": "other-mcp"}},
                }
            )
        )
        output = setup_agent("gemini", str(tmp_path), mode="readonly", write=True, scope="project")
        assert "Config written" in output
        result = json.loads(settings.read_text())
        assert result["theme"] == "dark"
        assert result["mcpServers"]["other"]["command"] == "other-mcp"
        assert result["mcpServers"]["kicad"]["command"] == "uvx"
        assert result["mcpServers"]["kicad"]["env"]["KICAD_MCP_OPERATING_MODE"] == "readonly"

    def test_claude_desktop_windows_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sys, "platform", "win32")
        monkeypatch.setenv("APPDATA", "C:\\Users\\Test\\AppData\\Roaming")
        path = resolve_path("claude-desktop", "user")
        assert (
            path
            == Path("C:\\Users\\Test\\AppData\\Roaming") / "Claude" / "claude_desktop_config.json"
        )

    def test_claude_desktop_macos_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sys, "platform", "darwin")
        path = resolve_path("claude-desktop", "user")
        assert (
            path
            == Path.home()
            / "Library"
            / "Application Support"
            / "Claude"
            / "claude_desktop_config.json"
        )

    def test_claude_desktop_linux_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sys, "platform", "linux")
        path = resolve_path("claude-desktop", "user")
        # Check for ".config" path segment (OS-agnostic)
        assert ".config" in str(path).replace("\\", "/")
        assert path == Path.home() / ".config" / "Claude" / "claude_desktop_config.json"

    def test_invalid_scope_raises(self) -> None:
        with pytest.raises(ValueError, match="does not support scope"):
            resolve_path("vscode", "user")  # vscode only supports project

    def test_remote_agent_no_scopes(self) -> None:
        with pytest.raises(ValueError):
            resolve_path("chatgpt", "project")


# ---------------------------------------------------------------------------
# Config generation
# ---------------------------------------------------------------------------


class TestGenerateConfig:
    def test_generate_claude_code(self) -> None:
        config, fmt = generate_config("claude-code", "/home/user/project", "readonly")
        assert fmt == "json"
        data = json.loads(config)
        assert "mcpServers" in data
        assert "kicad" in data["mcpServers"]

    def test_generate_codex_toml(self) -> None:
        toml_str = _generate_codex_toml("/home/user/project", "readonly")
        server = tomllib.loads(toml_str)["mcp_servers"]["kicad"]
        assert server["command"] == "uvx"
        assert server["args"] == ["kicad-mcp-pro", "--transport", "stdio"]
        assert server["env"]["KICAD_MCP_PROFILE"] == "default"
        assert server["env"]["KICAD_MCP_OPERATING_MODE"] == "readonly"
        assert server["env"]["KICAD_MCP_PROJECT_DIR"] == "/home/user/project"
        assert "cwd" not in server
        assert "default_tools_approval_mode" not in server

    def test_generate_vscode(self) -> None:
        config, fmt = generate_config("vscode", "/home/user/project", "readonly")
        assert fmt == "json"
        data = json.loads(config)
        assert "servers" in data
        assert "${workspaceFolder}" in config

    def test_generate_opencode(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("kicad_mcp.setup._opencode_uses_v2", lambda: True)
        config, fmt = generate_config("opencode", "/home/user/project", "write")
        assert fmt == "json"
        server = json.loads(config)["mcp"]["servers"]["kicad"]
        assert server["type"] == "local"
        assert server["command"] == ["uvx", "kicad-mcp-pro", "--transport", "stdio"]
        assert server["environment"]["KICAD_MCP_OPERATING_MODE"] == "write"
        assert server["codemode"] is False
        assert "enabled" not in server

    def test_generate_opencode_v1(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("kicad_mcp.setup._opencode_uses_v2", lambda: False)
        config, _ = generate_config("opencode", "/home/user/project")
        server = json.loads(config)["mcp"]["kicad"]
        assert server["type"] == "local"
        assert server["command"] == "uvx"
        assert server["args"] == ["kicad-mcp-pro"]
        assert server["enabled"] is True

    @pytest.mark.parametrize(
        ("setting", "expected"),
        [("1", False), ("2", True), ("unexpected", True)],
    )
    def test_opencode_explicit_legacy_selection(
        self, monkeypatch: pytest.MonkeyPatch, setting: str, expected: bool
    ) -> None:
        monkeypatch.setenv("KICAD_MCP_OPENCODE_CONFIG_VERSION", setting)
        assert _opencode_uses_v2() is expected

    def test_opencode_default_v2(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("KICAD_MCP_OPENCODE_CONFIG_VERSION", raising=False)
        assert _opencode_uses_v2()

    def test_generate_opencode_v2_remote(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("kicad_mcp.setup._opencode_uses_v2", lambda: True)
        config, _ = generate_config("opencode", "/home/user/project", transport="http")
        server = json.loads(config)["mcp"]["servers"]["kicad-cloud"]
        assert server["type"] == "remote"
        assert server["url"].startswith("http://127.0.0.1:")
        assert "enabled" not in server

    def test_generate_remote_chatgpt(self) -> None:
        config, fmt = generate_config("chatgpt", "", url="https://example.com/mcp")
        assert fmt == "json"
        assert "https://example.com/mcp" in config

    def test_generate_remote_claude_ai(self) -> None:
        config, fmt = generate_config("claude-ai", "")
        assert "claude-ai" in config or "Custom Connector" in config

    def test_unknown_agent_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="Unsupported agent"):
            generate_config("unknown-agent", str(tmp_path))

    def test_env_for_mode(self) -> None:
        env = _env_for_mode("readonly", "/project")
        assert env["KICAD_MCP_PROFILE"] == "default"
        assert env["KICAD_MCP_OPERATING_MODE"] == "readonly"
        assert env["KICAD_MCP_PROJECT_DIR"] == "/project"

        env2 = _env_for_mode("write", "/other")
        assert env2["KICAD_MCP_PROFILE"] == "build"
        assert env2["KICAD_MCP_OPERATING_MODE"] == "write"
        assert env2["KICAD_MCP_PROJECT_DIR"] == "/other"

        env3 = _env_for_mode("manufacturing", "/release")
        assert env3["KICAD_MCP_PROFILE"] == "release"
        assert env3["KICAD_MCP_OPERATING_MODE"] == "manufacturing"
        assert env3["KICAD_MCP_PROJECT_DIR"] == "/release"


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


class TestValidateConfig:
    def test_valid_claude_code_config(self) -> None:
        config = json.dumps({"mcpServers": {"kicad": {"command": "uvx"}}})
        issues = validate_config(config, "claude-code", "json")
        assert issues == []

    def test_invalid_empty_config(self) -> None:
        issues = validate_config("", "claude-code", "json")
        assert len(issues) > 0

    def test_invalid_missing_mcp_servers(self) -> None:
        config = json.dumps({"foo": "bar"})
        issues = validate_config(config, "claude-code", "json")
        assert any("mcpServers" in i for i in issues)

    def test_valid_vscode_config(self) -> None:
        config = json.dumps({"servers": {"kicad": {"type": "stdio"}}})
        issues = validate_config(config, "vscode", "json")
        assert issues == []

    def test_valid_opencode_config(self) -> None:
        config = json.dumps({"mcp": {"kicad": {"type": "local"}}})
        issues = validate_config(config, "opencode", "json")
        assert issues == []

    def test_opencode_v2_invalid_server_map(self) -> None:
        config = json.dumps({"mcp": {"servers": []}})
        assert validate_config(config, "opencode", "json") == [
            'OpenCode V2 "mcp.servers" must be an object.'
        ]

    def test_codex_toml_validation(self, tmp_path: Path) -> None:
        toml = _generate_codex_toml(str(tmp_path), "readonly")
        issues = validate_config(toml, "codex", "toml")
        assert issues == []

    def test_codex_toml_missing_section(self) -> None:
        issues = validate_config("command = 'uvx'", "codex", "toml")
        assert len(issues) > 0


# ---------------------------------------------------------------------------
# Backup / restore
# ---------------------------------------------------------------------------


class TestBackupRestore:
    def test_backup_creates_copy(self, tmp_path: Path) -> None:
        config_file = tmp_path / "test.json"
        config_file.write_text('{"original": true}')
        bak = backup_config(config_file)
        assert bak is not None
        assert bak.exists()
        assert json.loads(bak.read_text()) == {"original": True}

    def test_backup_nonexistent_file(self, tmp_path: Path) -> None:
        config_file = tmp_path / "nonexistent.json"
        bak = backup_config(config_file)
        assert bak is None

    def test_list_backups(self, tmp_path: Path) -> None:
        config_file = tmp_path / "config.json"
        config_file.write_text("{}")
        backup_config(config_file)
        backups = list_backups_helper(tmp_path / "config.json")
        assert len(backups) >= 1

    def test_restore_backup(self, tmp_path: Path) -> None:
        config_file = tmp_path / "config.json"
        config_file.write_text("original")
        bak = backup_config(config_file)
        assert bak is not None
        config_file.write_text("modified")
        assert config_file.read_text() == "modified"
        # Simulate restore
        import shutil

        shutil.copy2(bak, config_file)
        assert config_file.read_text() == "original"


def list_backups_helper(path: Path) -> list[Path]:
    """Helper to list backup files for a given path."""
    parent = path.parent
    if not parent.exists():
        return []
    pattern = f"{path.name}.*.bak"
    return sorted(parent.glob(pattern), reverse=True)


class TestWriteConfig:
    def test_write_config_creates_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        old_cwd = Path.cwd()
        try:
            __import__("os").chdir(str(tmp_path))
            monkeypatch.setattr("kicad_mcp.setup.resolve_path", lambda k, s: tmp_path / ".mcp.json")

            config_content = '{"mcpServers": {"kicad": {}}}'
            path_str, ok = write_config("claude-code", config_content, "project", backup=False)
            assert ok, path_str
            assert Path(path_str).exists()
        finally:
            __import__("os").chdir(str(old_cwd))

    def test_opencode_v2_merge_preserves_unrelated_servers(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("kicad_mcp.setup._opencode_uses_v2", lambda: True)
        target = tmp_path / "opencode.json"
        target.write_text(
            json.dumps(
                {
                    "theme": "dark",
                    "mcp": {
                        "servers": {"other": {"type": "remote", "url": "https://example.com/mcp"}},
                        "legacy-server": {"type": "local"},
                    },
                }
            ),
            encoding="utf-8",
        )
        config, _ = generate_config("opencode", str(tmp_path))
        path, ok = write_config("opencode", config, "project", backup=False, project_dir=tmp_path)
        assert ok, path
        merged = json.loads(target.read_text(encoding="utf-8"))
        assert merged["theme"] == "dark"
        assert merged["mcp"]["servers"]["other"]["type"] == "remote"
        assert merged["mcp"]["servers"]["kicad"]["type"] == "local"
        assert merged["mcp"]["legacy-server"]["type"] == "local"

    def test_write_remote_agent_fails(self) -> None:
        path_str, ok = write_config("chatgpt", "{}", "project")
        assert not ok
        assert "remote-only" in path_str

    def test_write_invalid_scope(self) -> None:
        path_str, ok = write_config("vscode", "{}", "user")
        assert not ok


# ---------------------------------------------------------------------------
# Agent config check (doctor integration)
# ---------------------------------------------------------------------------


class TestCheckAgentConfig:
    def test_check_remote_agent_returns_note(self) -> None:
        result = check_agent_config("chatgpt")
        assert result["key"] == "chatgpt"
        assert result.get("note") == "remote-only"

    def test_check_agent_returns_paths(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        old_cwd = Path.cwd()
        try:
            __import__("os").chdir(str(tmp_path))
            mcp_json = tmp_path / ".mcp.json"
            mcp_json.write_text('{"mcpServers": {"kicad": {}}}')
            monkeypatch.setattr("kicad_mcp.setup.resolve_path", lambda k, s: mcp_json)

            result = check_agent_config("claude-code")
            configs = result.get("configs", {})
            assert isinstance(configs, dict)
        finally:
            __import__("os").chdir(str(old_cwd))

    def test_check_all_agents_returns_list(self) -> None:
        results = check_all_agent_configs()
        assert isinstance(results, list)
        # Should include local agents
        keys = [r["key"] for r in results]
        assert "claude-code" in keys
        assert "chatgpt" not in keys  # remote excluded


@pytest.mark.parametrize(
    ("agent_key", "config", "expected"),
    [
        ("vscode", "{}", ['Missing top-level "servers" key (expected for VS Code).']),
        ("vscode", '{"servers":{}}', ['Missing "servers.kicad" entry.']),
        ("vscode", '{"servers":{"kicad":{}}}', []),
        ("opencode", "{}", ['Missing top-level "mcp" key (expected for OpenCode).']),
        ("opencode", '{"mcp":{}}', []),
        ("codex", "{}", []),
        ("claude-code", "{}", ['Missing top-level "mcpServers" key.']),
        ("claude-code", '{"mcpServers":{}}', ['Missing "mcpServers.kicad" entry.']),
        ("claude-code", '{"mcpServers":{"kicad":{}}}', []),
    ],
)
def test_json_agent_config_validation_preserves_legacy_results(
    agent_key: str, config: str, expected: list[str]
) -> None:
    assert validate_config(config, agent_key, "json") == expected


@pytest.mark.parametrize(
    ("issues", "warning_text"),
    [
        ([], ""),
        (["first", "second"], "\n⚠ Config written but has 2 issue(s):\n  - first\n  - second"),
    ],
)
def test_setup_write_validation_message_is_unchanged(
    monkeypatch: pytest.MonkeyPatch, issues: list[str], warning_text: str
) -> None:
    monkeypatch.setattr(
        "kicad_mcp.setup.write_config", lambda *args, **kwargs: ("config.json", True)
    )
    monkeypatch.setattr("kicad_mcp.setup.validate_config", lambda *args: issues)
    snippet, _ = generate_config("claude-code", "/safe/project")
    assert setup_agent("claude-code", project_dir="/safe/project", write=True) == (
        f"✓ Config written to config.json{warning_text}\n\n{snippet}"
    )


# ---------------------------------------------------------------------------
# CLI commands
# ---------------------------------------------------------------------------


class TestCliSetup:
    def test_setup_claude_code_preview(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("kicad_mcp.setup.shutil.which", lambda _: None)
        result = CliRunner().invoke(app, ["setup", "claude-code"])
        assert result.exit_code == 0, result.output
        assert "uvx" in result.output or "kicad-mcp-pro" in result.output

    def test_setup_codex_preview(self) -> None:
        result = CliRunner().invoke(app, ["setup", "codex"])
        assert result.exit_code == 0, result.output
        assert "[mcp_servers.kicad]" in result.output

    def test_setup_unknown_agent(self) -> None:
        result = CliRunner().invoke(app, ["setup", "unknown-agent"])
        assert "Unsupported agent" in result.output

    def test_setup_wizard_command(self) -> None:
        result = CliRunner().invoke(app, ["setup", "wizard"])
        assert result.exit_code == 0, result.output
        assert "KiCad MCP Setup Wizard" in result.output or "Agent" in result.output

    def test_setup_interactive(self) -> None:
        result = CliRunner().invoke(app, ["setup", "interactive"])
        assert result.exit_code == 0, result.output
        assert "Supported agents" in result.output

    def test_setup_restore_non_existent(self) -> None:
        result = CliRunner().invoke(app, ["setup-restore", "claude-code"])
        assert result.exit_code == 0, result.output

    def test_setup_backups_non_existent(self) -> None:
        result = CliRunner().invoke(app, ["setup-backups", "claude-code"])
        assert result.exit_code == 0, result.output

    def test_setup_backup_commands_forward_project_dir(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        observed: list[tuple[str, str | None]] = []
        monkeypatch.setattr(
            "kicad_mcp.setup.restore_config",
            lambda _agent, _scope, *, project_dir=None: (
                observed.append(("restore", project_dir)) or "ok"
            ),
        )
        monkeypatch.setattr(
            "kicad_mcp.setup.list_config_backups",
            lambda _agent, _scope, *, project_dir=None: (
                observed.append(("backups", project_dir)) or "ok"
            ),
        )

        project = str(tmp_path / "project")
        restored = CliRunner().invoke(app, ["setup-restore", "cursor", "--project-dir", project])
        listed = CliRunner().invoke(app, ["setup-backups", "cursor", "--project-dir", project])

        assert restored.exit_code == 0, restored.output
        assert listed.exit_code == 0, listed.output
        assert observed == [("restore", project), ("backups", project)]


# ---------------------------------------------------------------------------
# Doctor integration
# ---------------------------------------------------------------------------


class TestDoctorAgentChecks:
    def test_doctor_contains_agent_checks(self, monkeypatch: pytest.MonkeyPatch) -> None:

        monkeypatch.setattr("kicad_mcp.diagnostics.find_kicad_version", lambda _: "KiCad 10.0")
        monkeypatch.setattr(
            "kicad_mcp.diagnostics.get_board",
            lambda: (_ for _ in ()).throw(Exception("not reachable")),
        )

        result = CliRunner().invoke(app, ["doctor", "--json"])
        if result.exit_code == 0:
            import json

            payload = json.loads(result.output)
            check_names = [c["name"] for c in payload.get("checks", [])]
            agent_checks = [n for n in check_names if n.startswith("agent_config_")]
            # Agent config checks should be present in doctor mode
            assert len(agent_checks) > 0, f"No agent_config checks found in: {check_names}"


def test_claude_smoke_test_decodes_cli_output_as_utf8(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    import kicad_mcp.setup as setup_module

    observed: dict[str, object] = {}
    monkeypatch.setattr(setup_module.shutil, "which", lambda _: "claude")

    def fake_run(args: object, **kwargs: object) -> object:
        observed.update(kwargs)
        return SimpleNamespace(stdout="kicad")

    monkeypatch.setattr("subprocess.run", fake_run)

    result = setup_module._run_smoke_test("claude-code")

    assert observed["encoding"] == "utf-8"
    assert observed["errors"] == "replace"
    assert "shows kicad" in result

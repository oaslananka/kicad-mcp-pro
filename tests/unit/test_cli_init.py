"""Tests for kicad_mcp.cli_init module (interactive setup wizard)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from kicad_mcp.cli_init import (
    MCP_CLIENT_CONFIGS,
    _generate_mcp_config,
    _resolve_config_path,
    _write_kicad_mcp_config,
    _write_mcp_config,
)

# ---------------------------------------------------------------------------
# MCP_CLIENT_CONFIGS
# ---------------------------------------------------------------------------


class TestMcpClientConfigs:
    def test_all_clients_have_three_platforms(self) -> None:
        for client, paths in MCP_CLIENT_CONFIGS.items():
            assert "windows" in paths, f"{client} missing windows"
            assert "darwin" in paths, f"{client} missing darwin"
            assert "linux" in paths, f"{client} missing linux"

    def test_all_config_paths_are_strings(self) -> None:
        for client, paths in MCP_CLIENT_CONFIGS.items():
            for platform_key, path in paths.items():
                assert isinstance(path, str), f"{client}/{platform_key} not a string"
                assert path.strip(), f"{client}/{platform_key} is empty"


# ---------------------------------------------------------------------------
# _resolve_config_path
# ---------------------------------------------------------------------------


class TestResolveConfigPath:
    def test_unknown_client_returns_none(self) -> None:
        assert _resolve_config_path("nonexistent-client") is None

    def test_known_client_returns_path(self) -> None:
        path = _resolve_config_path("claude-desktop")
        assert path is not None
        assert isinstance(path, Path)
        # Path should be absolute after expandvars/expanduser
        assert str(path).startswith("/") or (":" in str(path)[:3])  # unix or windows


# ---------------------------------------------------------------------------
# _generate_mcp_config
# ---------------------------------------------------------------------------


class TestGenerateMcpConfig:
    def test_http_transport(self) -> None:
        result = _generate_mcp_config("streamable-http", 3334)
        mcp = result["mcpServers"]["kicad-mcp-pro"]
        assert mcp["command"] == "uvx"
        assert "streamable-http" in mcp["args"]
        assert mcp["env"] == {}

    def test_stdio_transport(self) -> None:
        result = _generate_mcp_config("stdio", 3334)
        mcp = result["mcpServers"]["kicad-mcp-pro"]
        assert mcp["command"] == "uvx"
        assert "stdio" not in mcp["args"]  # stdio uses just the package name

    def test_custom_version(self) -> None:
        result = _generate_mcp_config("streamable-http", 8080, version="4.0.0")
        mcp = result["mcpServers"]["kicad-mcp-pro"]
        assert any("4.0.0" in arg for arg in mcp["args"])

    def test_output_is_valid_json(self) -> None:
        result = _generate_mcp_config("streamable-http", 3334)
        # Should be serializable
        json.dumps(result)
        assert "mcpServers" in result


# ---------------------------------------------------------------------------
# _write_mcp_config
# ---------------------------------------------------------------------------


class TestWriteMcpConfig:
    def test_unknown_client_returns_none(self) -> None:
        result = _write_mcp_config("nonexistent", {"mcpServers": {}})
        assert result is None

    def test_creates_new_file(self, tmp_path: Path) -> None:
        # Point config to a temp location by patching
        import kicad_mcp.cli_init as cli_init

        orig_resolve = cli_init._resolve_config_path

        def mock_resolve(client: str) -> Path | None:
            return tmp_path / "config.json"

        cli_init._resolve_config_path = mock_resolve
        try:
            snippet = _generate_mcp_config("streamable-http", 3334)
            result = _write_mcp_config("cursor", snippet)
            assert result is not None
            assert result.exists()
            data = json.loads(result.read_text(encoding="utf-8"))
            assert "mcpServers" in data
            assert "kicad-mcp-pro" in data["mcpServers"]
        finally:
            cli_init._resolve_config_path = orig_resolve

    def test_merges_existing_file(self, tmp_path: Path) -> None:
        import kicad_mcp.cli_init as cli_init

        orig_resolve = cli_init._resolve_config_path

        config_path = tmp_path / "config.json"
        config_path.write_text(
            json.dumps({"mcpServers": {"existing-agent": {"command": "npx"}}}, indent=2),
            encoding="utf-8",
        )

        def mock_resolve(client: str) -> Path | None:
            return config_path

        cli_init._resolve_config_path = mock_resolve
        try:
            snippet = _generate_mcp_config("streamable-http", 3334)
            result = _write_mcp_config("cursor", snippet)
            assert result is not None
            data = json.loads(result.read_text(encoding="utf-8"))
            assert "existing-agent" in data["mcpServers"]
            assert "kicad-mcp-pro" in data["mcpServers"]
        finally:
            cli_init._resolve_config_path = orig_resolve


# ---------------------------------------------------------------------------
# _write_kicad_mcp_config
# ---------------------------------------------------------------------------


class TestWriteKicadMcpConfig:
    def test_writes_config(self, tmp_path: Path) -> None:
        output = tmp_path / "kicad-mcp" / "config.json"
        kicad_path = Path("/usr/local/bin/kicad-cli")  # noqa: S108
        result = _write_kicad_mcp_config(kicad_path, "streamable-http", 3334, output=output)
        assert result == output
        assert output.exists()
        data = json.loads(output.read_text(encoding="utf-8"))
        assert data["kicad_path"] == str(kicad_path)
        assert data["transport"] == "streamable-http"
        assert data["port"] == 3334

    def test_default_path_uses_home_dir(self) -> None:
        kicad_path = Path("/usr/local/bin/kicad-cli")  # noqa: S108
        result = _write_kicad_mcp_config(kicad_path, "stdio", 0)
        expected = Path.home() / ".kicad-mcp" / "config.json"
        assert result == expected
        assert result.exists()
        result.unlink()
        # Clean up parent if empty
        result.parent.rmdir()


# ---------------------------------------------------------------------------------------------
# Interactive helper coverage
# ---------------------------------------------------------------------------------------------


def test_run_wizard_yes_mode_writes_selected_client_and_summary(
    monkeypatch,
    tmp_path: Path,
) -> None:
    import kicad_mcp.cli_init as cli_init

    kicad_path = Path("/usr/bin/kicad-cli")  # noqa: S108
    client_path = tmp_path / "client.json"
    output = tmp_path / "config.json"

    monkeypatch.setattr(cli_init, "_detect_kicad_interactive", lambda console, yes: kicad_path)
    monkeypatch.setattr(
        cli_init,
        "_select_transport_interactive",
        lambda console, yes: (cli_init.TRANSPORT_STREAMABLE_HTTP, 4444),
    )
    monkeypatch.setattr(
        cli_init,
        "_select_client_interactive",
        lambda console, yes: (cli_init.CLIENT_CURSOR, "Cursor"),
    )
    monkeypatch.setattr(cli_init, "_write_mcp_config", lambda client, snippet: client_path)

    cli_init.run_wizard(yes=True, output=output)

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload == {
        "kicad_path": str(kicad_path),
        "transport": cli_init.TRANSPORT_STREAMABLE_HTTP,
        "port": 4444,
    }


def test_detect_kicad_interactive_accepts_detected_path(monkeypatch) -> None:
    from rich.console import Console

    import kicad_mcp.cli_init as cli_init

    expected = Path("/opt/kicad/bin/kicad-cli")  # noqa: S108
    monkeypatch.setattr(cli_init, "discover_kicad_cli", lambda: expected)
    monkeypatch.setattr(cli_init, "find_kicad_version", lambda path: "10.0.6")
    monkeypatch.setattr(cli_init.typer, "confirm", lambda *args, **kwargs: True)

    assert cli_init._detect_kicad_interactive(Console(), yes=False) == expected


def test_detect_kicad_interactive_manual_retry(monkeypatch, tmp_path: Path) -> None:
    from rich.console import Console

    import kicad_mcp.cli_init as cli_init

    responses = iter([str(tmp_path / "missing"), str(tmp_path)])
    monkeypatch.setattr(
        cli_init,
        "discover_kicad_cli",
        lambda: (_ for _ in ()).throw(RuntimeError("not found")),
    )
    monkeypatch.setattr(cli_init.typer, "prompt", lambda *args, **kwargs: next(responses))

    assert cli_init._detect_kicad_interactive(Console(), yes=False) == tmp_path


def test_detect_kicad_interactive_manual_cancel(monkeypatch) -> None:
    from rich.console import Console

    import kicad_mcp.cli_init as cli_init

    monkeypatch.setattr(cli_init, "discover_kicad_cli", lambda: Path("/opt/kicad-cli"))
    monkeypatch.setattr(cli_init, "find_kicad_version", lambda path: "10.0.6")
    monkeypatch.setattr(cli_init.typer, "prompt", lambda *args, **kwargs: "")

    assert cli_init._detect_kicad_interactive(Console(), yes=True) is None


def test_select_transport_interactive_yes_mode() -> None:
    from rich.console import Console

    import kicad_mcp.cli_init as cli_init

    assert cli_init._select_transport_interactive(Console(), yes=True) == (
        cli_init.TRANSPORT_STREAMABLE_HTTP,
        cli_init.DEFAULT_HTTP_PORT,
    )


def test_select_transport_interactive_http_custom_port(monkeypatch) -> None:
    from rich.console import Console

    import kicad_mcp.cli_init as cli_init

    responses = iter(["1", 4567])
    monkeypatch.setattr(cli_init.typer, "prompt", lambda *args, **kwargs: next(responses))

    assert cli_init._select_transport_interactive(Console(), yes=False) == (
        cli_init.TRANSPORT_STREAMABLE_HTTP,
        4567,
    )


def test_select_transport_interactive_stdio(monkeypatch) -> None:
    from rich.console import Console

    import kicad_mcp.cli_init as cli_init

    monkeypatch.setattr(cli_init.typer, "prompt", lambda *args, **kwargs: "2")

    assert cli_init._select_transport_interactive(Console(), yes=False) == (
        cli_init.TRANSPORT_STDIO,
        cli_init.DEFAULT_HTTP_PORT,
    )


def test_select_client_interactive_yes_detects_existing_config(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from rich.console import Console

    import kicad_mcp.cli_init as cli_init

    existing = tmp_path / "client.json"
    existing.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(cli_init, "_resolve_config_path", lambda client: existing)

    client, display = cli_init._select_client_interactive(Console(), yes=True)

    assert client == next(iter(cli_init.MCP_CLIENT_CONFIGS))
    assert display == dict(cli_init.CLIENT_DISPLAY_NAMES).get(client, client)


def test_select_client_interactive_yes_falls_back_to_claude(monkeypatch) -> None:
    from rich.console import Console

    import kicad_mcp.cli_init as cli_init

    monkeypatch.setattr(cli_init, "_resolve_config_path", lambda client: None)

    client, display = cli_init._select_client_interactive(Console(), yes=True)

    assert client == cli_init.CLIENT_CLAUDE_DESKTOP
    assert display == dict(cli_init.CLIENT_DISPLAY_NAMES)[cli_init.CLIENT_CLAUDE_DESKTOP]


def test_select_client_interactive_skip(monkeypatch) -> None:
    from rich.console import Console

    import kicad_mcp.cli_init as cli_init

    choice = str(len(cli_init.MCP_CLIENT_CONFIGS) + 1)
    monkeypatch.setattr(cli_init.typer, "prompt", lambda *args, **kwargs: choice)

    assert cli_init._select_client_interactive(Console(), yes=False) == (
        cli_init.CLIENT_NONE,
        cli_init.CLIENT_SKIPPED_DISPLAY,
    )


def test_select_client_interactive_numeric_and_direct_name(monkeypatch) -> None:
    from rich.console import Console

    import kicad_mcp.cli_init as cli_init

    clients = list(cli_init.MCP_CLIENT_CONFIGS)
    responses = iter(["1", clients[-1]])
    monkeypatch.setattr(cli_init.typer, "prompt", lambda *args, **kwargs: next(responses))

    first, _ = cli_init._select_client_interactive(Console(), yes=False)
    direct, _ = cli_init._select_client_interactive(Console(), yes=False)

    assert first == clients[0]
    assert direct == clients[-1]


def test_select_client_interactive_display_name_and_invalid_fallback(monkeypatch) -> None:
    from rich.console import Console

    import kicad_mcp.cli_init as cli_init

    display_map = dict(cli_init.CLIENT_DISPLAY_NAMES)
    display = next(iter(display_map.values()))
    responses = iter([display, "definitely-invalid"])
    monkeypatch.setattr(cli_init.typer, "prompt", lambda *args, **kwargs: next(responses))

    by_display, selected_display = cli_init._select_client_interactive(Console(), yes=False)
    fallback, _ = cli_init._select_client_interactive(Console(), yes=False)

    assert selected_display.lower() == display.lower()
    assert by_display in cli_init.MCP_CLIENT_CONFIGS
    assert fallback == cli_init.CLIENT_CLAUDE_DESKTOP


def test_run_wizard_exits_when_kicad_path_is_missing(monkeypatch, tmp_path: Path) -> None:
    import kicad_mcp.cli_init as cli_init

    monkeypatch.setattr(cli_init, "_detect_kicad_interactive", lambda console, yes: None)

    with pytest.raises(cli_init.typer.Exit) as exc_info:
        cli_init.run_wizard(yes=True, output=tmp_path / "config.json")

    assert exc_info.value.exit_code == 1


def test_run_wizard_warns_when_client_config_cannot_be_written(
    monkeypatch,
    tmp_path: Path,
) -> None:
    import kicad_mcp.cli_init as cli_init

    output = tmp_path / "config.json"
    monkeypatch.setattr(
        cli_init,
        "_detect_kicad_interactive",
        lambda console, yes: Path("/usr/bin/kicad-cli"),  # noqa: S108
    )
    monkeypatch.setattr(
        cli_init,
        "_select_transport_interactive",
        lambda console, yes: (cli_init.TRANSPORT_STDIO, cli_init.DEFAULT_HTTP_PORT),
    )
    monkeypatch.setattr(
        cli_init,
        "_select_client_interactive",
        lambda console, yes: (cli_init.CLIENT_CURSOR, "Cursor"),
    )
    monkeypatch.setattr(cli_init, "_write_mcp_config", lambda client, snippet: None)

    cli_init.run_wizard(yes=True, output=output)

    assert output.exists()

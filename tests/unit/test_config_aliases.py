from __future__ import annotations

from pathlib import Path

import pytest

from kicad_mcp.config import KiCadMCPConfig


def test_config_aliases_and_secret_masking(fake_cli: Path, monkeypatch) -> None:
    workspace = fake_cli.parent
    socket_path = fake_cli.parent / "api.sock"
    monkeypatch.setenv("KICAD_API_SOCKET", str(socket_path))
    monkeypatch.setenv("KICAD_API_TOKEN", "secret-token")
    monkeypatch.setenv("KICAD_CLI_PATH", str(fake_cli))
    monkeypatch.setenv("KICAD_MCP_TIMEOUT_MS", "15000")
    monkeypatch.setenv("KICAD_MCP_RETRIES", "4")
    monkeypatch.setenv("KICAD_MCP_HEADLESS", "true")
    monkeypatch.setenv("KICAD_MCP_WORKSPACE_ROOT", str(workspace))
    monkeypatch.setenv("KICAD_MCP_LOG_LEVEL", "debug")

    cfg = KiCadMCPConfig()
    safe = cfg.safe_diagnostics()

    assert cfg.kicad_cli == fake_cli
    assert cfg.kicad_socket_path == socket_path
    assert cfg.kicad_token == "secret-token"  # noqa: S105 - test fixture
    assert cfg.timeout_ms == 15000
    assert cfg.ipc_retries == 4
    assert cfg.headless is True
    assert cfg.log_level == "DEBUG"
    assert safe["kicad_token"] == {"configured": True}
    assert "secret-token" not in str(safe)


@pytest.mark.parametrize(
    "endpoint",
    [
        r"ipc://C:\Users\Admin\AppData\Local\Temp\kicad\api.sock",
        "ipc://C:/Users/Admin/AppData/Local/Temp/kicad/api.sock",
        "ipc:///tmp/kicad/api.sock",
        "tcp://127.0.0.1:4242",
    ],
)
def test_explicit_ipc_endpoint_uri_round_trips_unchanged(
    endpoint: str,
    fake_cli: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("KICAD_API_SOCKET", endpoint)

    cfg = KiCadMCPConfig(kicad_cli=fake_cli)

    assert cfg.kicad_socket_path == endpoint


def test_invalid_timeout_alias_is_rejected(monkeypatch) -> None:
    monkeypatch.setenv("KICAD_MCP_TIMEOUT_MS", "not-a-number")

    with pytest.raises(ValueError):
        KiCadMCPConfig()


def test_project_dir_env_prefers_canonical_project_over_numbered_duplicate(
    tmp_path: Path,
    fake_cli: Path,
    monkeypatch,
) -> None:
    project_dir = tmp_path / "light-noise-detektor"
    project_dir.mkdir()
    canonical = project_dir / "light-noise-detektor.kicad_pro"
    duplicate = project_dir / "light-noise-detektor 2.kicad_pro"
    canonical.touch()
    duplicate.touch()
    (project_dir / "light-noise-detektor.kicad_sch").touch()
    monkeypatch.setenv("KICAD_MCP_PROJECT_DIR", str(project_dir))

    cfg = KiCadMCPConfig(kicad_cli=fake_cli)

    assert cfg.project_file == canonical


def test_vscode_webview_origin_is_allowed(sample_project: Path) -> None:
    _ = sample_project
    cfg = KiCadMCPConfig(cors_origins="vscode-webview://kicad-studio")

    assert cfg.cors_origin_list == ["vscode-webview://kicad-studio"]

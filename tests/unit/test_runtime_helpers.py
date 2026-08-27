from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import kicad_mcp.connection as connection
from kicad_mcp.discovery import (
    CliCapabilities,
    discover_library_paths,
    find_kicad_version,
    find_recent_projects,
    get_cli_capabilities,
)
from kicad_mcp.server import main_callback
from kicad_mcp.utils.logging import setup_logging

DOCKER_BIND_HOST = "0.0.0.0"  # noqa: S104 - regression fixture for Docker env preservation.
STRONG_ENV_TOKEN = "".join(("0123456789abcdef", "0123456789ABCDEF"))


def test_setup_logging_smoke() -> None:
    setup_logging("DEBUG", "json")
    setup_logging("INFO", "console")


def test_main_callback_runs_streamable_http(sample_project: Path, monkeypatch) -> None:
    fake_server = MagicMock()
    monkeypatch.setattr(
        "kicad_mcp.server.build_server",
        lambda profile, *, defer_registration=False: fake_server,
    )
    monkeypatch.setattr("kicad_mcp.server.setup_logging", lambda *args: None)

    main_callback(
        transport="http",
        host="127.0.0.1",
        port=4444,
        project_dir=str(sample_project),
        log_level="DEBUG",
        log_format="json",
        profile="minimal",
        experimental=True,
    )

    fake_server.run.assert_called_once_with(transport="streamable-http", mount_path="/mcp")


def test_main_callback_runs_stdio(sample_project: Path, monkeypatch) -> None:
    fake_server = MagicMock()
    monkeypatch.setattr(
        "kicad_mcp.server.build_server",
        lambda profile, *, defer_registration=False: fake_server,
    )
    monkeypatch.setattr("kicad_mcp.server.setup_logging", lambda *args: None)

    main_callback(
        transport="stdio",
        host="127.0.0.1",
        port=3334,
        project_dir=str(sample_project),
        log_level="INFO",
        log_format="console",
        profile="full",
        experimental=False,
    )

    fake_server.run.assert_called_once_with(transport="stdio")


def test_main_callback_preserves_env_when_cli_options_missing(
    sample_project: Path,
    monkeypatch,
) -> None:
    fake_server = MagicMock()
    profiles: list[str] = []
    monkeypatch.setenv("KICAD_MCP_TRANSPORT", "http")
    monkeypatch.setenv("KICAD_MCP_HOST", DOCKER_BIND_HOST)
    monkeypatch.setenv("KICAD_MCP_AUTH_TOKEN", STRONG_ENV_TOKEN)
    monkeypatch.setenv("KICAD_MCP_HTTP_BOUNDARY", "loopback-proxy")
    monkeypatch.setenv("KICAD_MCP_PUBLIC_BASE_URL", "http://127.0.0.1:4444")
    monkeypatch.setenv("KICAD_MCP_PORT", "4444")
    monkeypatch.setenv("KICAD_MCP_LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("KICAD_MCP_LOG_FORMAT", "json")
    monkeypatch.setenv("KICAD_MCP_PROFILE", "pcb_only")
    monkeypatch.setenv("KICAD_MCP_ENABLE_EXPERIMENTAL_TOOLS", "true")
    monkeypatch.setenv("KICAD_MCP_PROJECT_DIR", str(sample_project))
    monkeypatch.setattr(
        "kicad_mcp.server.build_server",
        lambda profile, *, defer_registration=False: profiles.append(profile) or fake_server,
    )
    monkeypatch.setattr("kicad_mcp.server.setup_logging", lambda *args: None)
    monkeypatch.setattr(
        "kicad_mcp.server._print_startup_diagnostics",
        lambda _cfg, *, probe_runtime=True: None,
    )

    main_callback(
        transport=None,
        host=None,
        port=None,
        project_dir=None,
        log_level=None,
        log_format=None,
        profile=None,
        experimental=None,
    )

    assert os.environ["KICAD_MCP_HOST"] == DOCKER_BIND_HOST
    assert os.environ["KICAD_MCP_PORT"] == "4444"
    assert os.environ["KICAD_MCP_HTTP_BOUNDARY"] == "loopback-proxy"
    assert os.environ["KICAD_MCP_PUBLIC_BASE_URL"] == "http://127.0.0.1:4444"
    assert os.environ["KICAD_MCP_PROFILE"] == "pcb_only"
    assert os.environ["KICAD_MCP_ENABLE_EXPERIMENTAL_TOOLS"] == "true"
    assert profiles == ["pcb_only"]
    fake_server.run.assert_called_once_with(transport="streamable-http", mount_path="/mcp")


def test_main_callback_explicit_cli_options_override_env(
    sample_project: Path,
    monkeypatch,
) -> None:
    fake_server = MagicMock()
    profiles: list[str] = []
    monkeypatch.setenv("KICAD_MCP_TRANSPORT", "http")
    monkeypatch.setenv("KICAD_MCP_HOST", DOCKER_BIND_HOST)
    monkeypatch.setenv("KICAD_MCP_PORT", "4444")
    monkeypatch.setenv("KICAD_MCP_PROFILE", "pcb_only")
    monkeypatch.setenv("KICAD_MCP_ENABLE_EXPERIMENTAL_TOOLS", "true")
    monkeypatch.setattr(
        "kicad_mcp.server.build_server",
        lambda profile, *, defer_registration=False: profiles.append(profile) or fake_server,
    )
    monkeypatch.setattr("kicad_mcp.server.setup_logging", lambda *args: None)
    monkeypatch.setattr(
        "kicad_mcp.server._print_startup_diagnostics",
        lambda _cfg, *, probe_runtime=True: None,
    )

    main_callback(
        transport="stdio",
        host="127.0.0.1",
        port=3334,
        project_dir=str(sample_project),
        log_level="INFO",
        log_format="console",
        profile="minimal",
        experimental=False,
    )

    assert os.environ["KICAD_MCP_TRANSPORT"] == "stdio"
    assert os.environ["KICAD_MCP_HOST"] == "127.0.0.1"
    assert os.environ["KICAD_MCP_PORT"] == "3334"
    assert os.environ["KICAD_MCP_PROFILE"] == "minimal"
    assert os.environ["KICAD_MCP_ENABLE_EXPERIMENTAL_TOOLS"] == "false"
    assert profiles == ["minimal"]
    fake_server.run.assert_called_once_with(transport="stdio")


def test_find_recent_projects_reads_kicad_config(tmp_path: Path, monkeypatch) -> None:
    project_dir = tmp_path / "projects"
    project_dir.mkdir()
    project_file = project_dir / "demo.kicad_pro"
    project_file.write_text("{}", encoding="utf-8")

    config_dir = tmp_path / ".config" / "kicad" / "10.0"
    config_dir.mkdir(parents=True)
    (config_dir / "kicad_common.json").write_text(
        '{"recentlyUsedFiles": {"projects": ["' + str(project_file).replace("\\", "\\\\") + '"]}}',
        encoding="utf-8",
    )

    monkeypatch.setattr("kicad_mcp.discovery.platform.system", lambda: "Linux")
    monkeypatch.setattr("kicad_mcp.discovery.Path.home", lambda: tmp_path)

    recent = find_recent_projects()

    assert recent == [project_file]


def test_discover_library_paths_from_cli_tree(tmp_path: Path) -> None:
    cli = tmp_path / "KiCad" / "bin" / "kicad-cli"
    cli.parent.mkdir(parents=True)
    cli.write_text("", encoding="utf-8")

    share_root = tmp_path / "KiCad" / "share" / "kicad"
    (share_root / "symbols").mkdir(parents=True)
    (share_root / "footprints").mkdir(parents=True)

    paths = discover_library_paths(cli)

    assert paths["symbols"] == share_root / "symbols"
    assert paths["footprints"] == share_root / "footprints"


def test_discover_library_paths_includes_windows_8_fallback(monkeypatch) -> None:
    expected_root = Path(r"C:\Program Files\KiCad\8.0\share\kicad")
    expected_symbols = expected_root / "symbols"
    expected_footprints = expected_root / "footprints"
    fake_existing = {expected_symbols, expected_footprints}

    monkeypatch.setattr("kicad_mcp.discovery.platform.system", lambda: "Windows")
    monkeypatch.setattr(
        "pathlib.Path.exists",
        lambda self: self in fake_existing,
    )

    paths = discover_library_paths(Path(r"C:\missing\kicad-cli.exe"))

    assert paths["symbols"] == expected_symbols
    assert paths["footprints"] == expected_footprints


def test_cli_version_and_capabilities_are_detected(tmp_path: Path, monkeypatch) -> None:
    cli = tmp_path / "kicad-cli"
    cli.write_text("", encoding="utf-8")

    def fake_run(
        cmd: list[str],
        capture_output: bool,
        text: bool,
        timeout: float,
        check: bool,
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        _ = (capture_output, text, timeout, check)
        _ = kwargs
        if "--version" in cmd:
            return subprocess.CompletedProcess(cmd, 0, stdout="KiCad 10.0.1", stderr="")
        help_blob = "gerbers Gerber files positions ipc2581 odb ODB++ svg dxf step render spice"
        return subprocess.CompletedProcess(cmd, 0, stdout=help_blob, stderr="")

    get_cli_capabilities.cache_clear()
    monkeypatch.setattr("kicad_mcp.discovery.subprocess.run", fake_run)

    assert find_kicad_version(cli) == "KiCad 10.0.1"
    caps = get_cli_capabilities(cli)

    assert caps == CliCapabilities(
        version="KiCad 10.0.1",
        gerber_command="gerbers",
        drill_command="drill",
        position_command="positions",
        supports_ipc2581=True,
        supports_odb_export=True,
        supports_svg=True,
        supports_dxf=True,
        supports_step=True,
        supports_render=True,
        supports_spice_netlist=True,
    )


def test_cli_capabilities_are_cached(tmp_path: Path, monkeypatch) -> None:
    cli = tmp_path / "kicad-cli"
    cli.write_text("", encoding="utf-8")
    calls: list[list[str]] = []

    def fake_run(
        cmd: list[str],
        capture_output: bool,
        text: bool,
        timeout: float,
        check: bool,
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        _ = (capture_output, text, timeout, check)
        _ = kwargs
        calls.append(cmd)
        if "--version" in cmd:
            return subprocess.CompletedProcess(cmd, 0, stdout="KiCad 10.0.1", stderr="")
        return subprocess.CompletedProcess(cmd, 0, stdout="gerbers positions", stderr="")

    get_cli_capabilities.cache_clear()
    monkeypatch.setattr("kicad_mcp.discovery.subprocess.run", fake_run)

    first = get_cli_capabilities(cli)
    second = get_cli_capabilities(cli)

    assert first == second
    assert len(calls) == 6


def test_cli_capabilities_cache_refreshes_when_binary_changes(tmp_path: Path, monkeypatch) -> None:
    cli = tmp_path / "kicad-cli"
    cli.write_text("", encoding="utf-8")
    calls: list[list[str]] = []

    def fake_run(
        cmd: list[str],
        capture_output: bool,
        text: bool,
        timeout: float,
        check: bool,
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        _ = (capture_output, text, timeout, check)
        _ = kwargs
        calls.append(cmd)
        if "--version" in cmd:
            return subprocess.CompletedProcess(cmd, 0, stdout="KiCad 10.0.1", stderr="")
        return subprocess.CompletedProcess(cmd, 0, stdout="gerbers positions", stderr="")

    get_cli_capabilities.cache_clear()
    monkeypatch.setattr("kicad_mcp.discovery.subprocess.run", fake_run)

    _ = get_cli_capabilities(cli)
    cli.write_text("changed", encoding="utf-8")
    now_ns = time.time_ns() + 1_000_000_000
    os.utime(cli, ns=(now_ns, now_ns))
    _ = get_cli_capabilities(cli)

    assert len(calls) == 12


def test_board_transaction_uses_reentrant_lock() -> None:
    assert connection._lock.acquire(timeout=0.1)
    try:
        assert connection._lock.acquire(blocking=False)
        connection._lock.release()
    finally:
        connection._lock.release()


def test_board_transaction_resets_connection_on_ipc_failure(monkeypatch) -> None:
    reset = MagicMock()
    sentinel = object()
    monkeypatch.setattr("kicad_mcp.connection.get_board", lambda: sentinel)
    monkeypatch.setattr("kicad_mcp.connection.reset_connection", reset)

    raised = False
    try:
        with connection.board_transaction() as board:
            assert board is sentinel
            raise connection.KiCadConnectionError("boom")
    except connection.KiCadConnectionError:
        raised = True

    assert raised
    reset.assert_called_once()


def test_reset_connection_closes_cached_instance(monkeypatch) -> None:
    closable = SimpleNamespace(close=MagicMock(side_effect=RuntimeError("close failed")))
    monkeypatch.setattr("kicad_mcp.connection._kicad", closable)

    connection.reset_connection()

    closable.close.assert_called_once()

from __future__ import annotations

import sys
import threading
from pathlib import Path

import pytest

from kicad_mcp.config import get_config
from kicad_mcp.connection import KiCadConnectionError
from kicad_mcp.server import (
    KiCadFastMCP,
    _ensure_thread_aware_stdout,
    _print_startup_diagnostics,
    build_server,
    main_callback,
)


def test_print_startup_diagnostics_logs_expected_fields(
    sample_project: Path,
    monkeypatch,
) -> None:
    _ = sample_project
    captured: dict[str, object] = {}

    def fake_info(event: str, **kwargs: object) -> None:
        captured["event"] = event
        captured["kwargs"] = kwargs

    monkeypatch.setattr("kicad_mcp.server.find_kicad_version", lambda _cli: "10.0.1")
    monkeypatch.setattr(
        "kicad_mcp.server.get_board",
        lambda: (_ for _ in ()).throw(KiCadConnectionError("IPC not reachable")),
    )
    monkeypatch.setattr("kicad_mcp.server.logger.info", fake_info)

    _print_startup_diagnostics(get_config())

    assert captured["event"] == "startup_diagnostics"
    payload = captured["kwargs"]
    assert payload["profile"] == "default"
    assert payload["kicad_version"] == "10.0.1"
    assert payload["gate_mode"] == "release-export-only"
    assert str(payload["project_dir"]).endswith("project")
    assert str(payload["ipc_status"]).startswith("unavailable")


def test_print_startup_diagnostics_warns_when_stdio_uses_auth_token(
    sample_project: Path,
    monkeypatch,
) -> None:
    _ = sample_project
    cfg = get_config()
    cfg.transport = "stdio"
    cfg.auth_token = "secret-token"  # noqa: S105 - regression fixture
    warnings: list[str] = []

    monkeypatch.setattr("kicad_mcp.server.find_kicad_version", lambda _cli: "10.0.1")
    monkeypatch.setattr(
        "kicad_mcp.server.get_board",
        lambda: (_ for _ in ()).throw(KiCadConnectionError("IPC not reachable")),
    )
    monkeypatch.setattr(
        "kicad_mcp.server.logger.warning",
        lambda event, **_kwargs: warnings.append(event),
    )
    monkeypatch.setattr("kicad_mcp.server.logger.info", lambda *_args, **_kwargs: None)

    _print_startup_diagnostics(cfg)

    assert warnings == ["stdio_auth_token_ignored"]


def test_main_callback_runs_startup_diagnostics_before_server_run(
    sample_project: Path,
    monkeypatch,
) -> None:
    _ = sample_project
    observed: dict[str, object] = {}

    class FakeServer:
        def start_lazy_registration_background(self) -> None:
            raise AssertionError("stdio startup must not run lazy registration in the background")

        def run(self, *, transport: str, mount_path: str | None = None) -> None:
            observed["transport"] = transport
            observed["mount_path"] = mount_path

    monkeypatch.setattr("kicad_mcp.server.setup_logging", lambda *_args: None)

    def fake_build_server(profile: str, *, defer_registration: bool = False) -> FakeServer:
        observed["build_profile"] = profile
        observed["defer_registration"] = defer_registration
        return FakeServer()

    monkeypatch.setattr("kicad_mcp.server.build_server", fake_build_server)

    def fake_diagnostics(cfg, *, probe_runtime: bool = True) -> None:
        observed["profile"] = cfg.profile
        observed["project_dir"] = cfg.project_dir
        observed["probe_runtime"] = probe_runtime

    monkeypatch.setattr("kicad_mcp.server._print_startup_diagnostics", fake_diagnostics)

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

    assert observed["profile"] == "full"
    assert observed["build_profile"] == "full"
    assert str(observed["project_dir"]).endswith("project")
    assert observed["defer_registration"] is True
    assert observed["probe_runtime"] is False
    assert observed["transport"] == "stdio"


def test_stdio_startup_routes_pre_run_stdout_to_stderr(
    sample_project: Path,
    monkeypatch,
    capsys,
) -> None:
    _ = sample_project
    observed: dict[str, object] = {}

    class FakeServer:
        def start_lazy_registration_background(self) -> None:
            raise AssertionError("stdio startup must not run lazy registration in the background")

        def run(self, *, transport: str, mount_path: str | None = None) -> None:
            observed["transport"] = transport
            observed["mount_path"] = mount_path

    monkeypatch.setattr("kicad_mcp.server.setup_logging", lambda *_args: None)
    monkeypatch.setattr(
        "kicad_mcp.server._print_startup_diagnostics",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr("kicad_mcp.server.logger.info", lambda *_args, **_kwargs: None)

    def fake_build_server(profile: str, *, defer_registration: bool = False) -> FakeServer:
        _ = profile, defer_registration
        print("2026-stdout-before-json")
        return FakeServer()

    monkeypatch.setattr("kicad_mcp.server.build_server", fake_build_server)

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

    captured = capsys.readouterr()
    assert "2026-stdout-before-json" not in captured.out
    assert "2026-stdout-before-json" in captured.err
    assert observed["transport"] == "stdio"


def test_lazy_registration_routes_stdout_to_stderr(capsys) -> None:
    server = KiCadFastMCP(name="kicad-mcp-pro-test")

    def register() -> None:
        print("2026-lazy-registration-before-json")

    server.set_lazy_registration(register)
    server.ensure_registered()

    captured = capsys.readouterr()
    assert "2026-lazy-registration-before-json" not in captured.out
    assert "2026-lazy-registration-before-json" in captured.err
    assert server._lazy_registration_complete is True


def test_lazy_registration_thread_does_not_capture_protocol_stdout(capsys) -> None:
    server = KiCadFastMCP(name="kicad-mcp-pro-test")
    started = threading.Event()
    release = threading.Event()

    def register() -> None:
        started.set()
        assert release.wait(timeout=5)
        print("2026-lazy-thread-before-json")

    server.set_lazy_registration(register)
    original_stdout = sys.stdout
    _ensure_thread_aware_stdout()
    try:
        thread = threading.Thread(target=server.ensure_registered)
        thread.start()
        assert started.wait(timeout=5)
        print("2026-json-rpc-response")
        release.set()
        thread.join(timeout=5)
    finally:
        sys.stdout = original_stdout

    assert not thread.is_alive()
    captured = capsys.readouterr()
    assert "2026-json-rpc-response" in captured.out
    assert "2026-json-rpc-response" not in captured.err
    assert "2026-lazy-thread-before-json" not in captured.out
    assert "2026-lazy-thread-before-json" in captured.err
    assert server._lazy_registration_complete is True


async def test_ensure_registered_async_times_out_on_hung_registration() -> None:
    # P5-T5: a registration that hangs must not block requests forever — the
    # awaiting handler gets a retryable timeout error and the thread is abandoned.
    from kicad_mcp.errors import ToolRegistrationTimeoutError

    server = KiCadFastMCP(name="kicad-mcp-pro-test")
    server._lazy_registration_timeout_s = 0.1
    release = threading.Event()

    def register() -> None:
        release.wait(timeout=5)  # blocks well past the 0.1s budget

    server.set_lazy_registration(register)
    try:
        with pytest.raises(ToolRegistrationTimeoutError) as exc_info:
            await server._ensure_registered_async()
        assert exc_info.value.code == "SERVER_INITIALIZING"
        assert exc_info.value.retryable is True
    finally:
        release.set()  # let the abandoned worker thread finish cleanly


def test_deferred_build_registers_tools_on_first_discovery(sample_project: Path) -> None:
    _ = sample_project
    server = build_server("minimal", defer_registration=True)

    assert isinstance(server, KiCadFastMCP)
    assert server._lazy_registration_complete is False

    tool_names = {tool.name for tool in server.list_tools_sync()}

    assert server._lazy_registration_complete is True
    assert "kicad_get_version" in tool_names
    assert "export_bom" in tool_names

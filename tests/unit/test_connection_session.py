from __future__ import annotations

from pathlib import Path

import pytest

import kicad_mcp.connection as connection
from kicad_mcp.config import KiCadMCPConfig
from kicad_mcp.errors import (
    KiCadBoardNotOpenError,
    KiCadConnectionTimeoutError,
    KiCadMcpError,
    KiCadNotRunningError,
)
from kicad_mcp.kicad.session import KiCadSession


def test_kicad_session_retries_without_real_kicad(fake_cli: Path) -> None:
    attempts = 0
    cfg = KiCadMCPConfig(kicad_cli=fake_cli, ipc_retries=2)

    class FakeClient:
        def get_board(self) -> str:
            return "board"

    def factory(**_kwargs: object) -> FakeClient:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise RuntimeError("not ready")
        return FakeClient()

    session = KiCadSession(
        client_factory=factory,
        config_factory=lambda: cfg,
        sleep=lambda _seconds: None,
    )

    assert session.board() == "board"
    assert attempts == 3


def test_kicad_session_builds_supported_kwargs_and_resets(tmp_path: Path, fake_cli: Path) -> None:
    credential = "configured-placeholder"
    cfg = KiCadMCPConfig(
        kicad_cli=fake_cli,
        kicad_socket_path=tmp_path / "api.sock",
        kicad_token=credential,
        ipc_connection_timeout=2.5,
    )

    class FakeClient:
        def __init__(
            self,
            socket_path: str,
            kicad_token: str,
            client_name: str,
            timeout_ms: int,
        ) -> None:
            self.socket_path = socket_path
            self.kicad_token = kicad_token
            self.client_name = client_name
            self.timeout_ms = timeout_ms
            self.closed = False

        def close(self) -> None:
            self.closed = True

    session = KiCadSession(client_factory=FakeClient, config_factory=lambda: cfg)

    client = session.client()

    assert isinstance(client, FakeClient)
    assert client.socket_path == str(tmp_path / "api.sock")
    assert client.kicad_token == credential
    assert client.client_name == "kicad-mcp"
    assert client.timeout_ms == 2500
    assert session.client() is client

    session.reset()

    assert client.closed is True


def test_kicad_session_preserves_explicit_ipc_uri(fake_cli: Path) -> None:
    endpoint = r"ipc://C:\Users\Admin\AppData\Local\Temp\kicad\api.sock"
    cfg = KiCadMCPConfig(kicad_cli=fake_cli, kicad_socket_path=endpoint)

    class FakeClient:
        def __init__(self, socket_path: str) -> None:
            self.socket_path = socket_path

    session = KiCadSession(client_factory=FakeClient, config_factory=lambda: cfg)

    client = session.client()

    assert isinstance(client, FakeClient)
    assert client.socket_path == endpoint


def test_kicad_session_maps_timeout(fake_cli: Path) -> None:
    cfg = KiCadMCPConfig(kicad_cli=fake_cli, ipc_retries=0)
    session = KiCadSession(
        client_factory=lambda **_kwargs: (_ for _ in ()).throw(TimeoutError("timed out")),
        config_factory=lambda: cfg,
        sleep=lambda _seconds: None,
    )

    with pytest.raises(KiCadConnectionTimeoutError):
        session.client()


def test_kicad_session_maps_unavailable(fake_cli: Path) -> None:
    cfg = KiCadMCPConfig(kicad_cli=fake_cli, ipc_retries=0)
    session = KiCadSession(
        client_factory=lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("refused")),
        config_factory=lambda: cfg,
        sleep=lambda _seconds: None,
    )

    with pytest.raises(KiCadNotRunningError):
        session.client()


def test_kicad_session_retries_busy_board_errors(fake_cli: Path) -> None:
    cfg = KiCadMCPConfig(kicad_cli=fake_cli, ipc_retries=2)
    attempts = 0

    class FakeClient:
        def get_board(self) -> str:
            nonlocal attempts
            attempts += 1
            if attempts < 3:
                raise RuntimeError("KiCad is busy and cannot respond to API requests right now")
            return "board"

    session = KiCadSession(
        client_factory=lambda **_kwargs: FakeClient(),
        config_factory=lambda: cfg,
        sleep=lambda _seconds: None,
    )

    assert session.board() == "board"
    assert attempts == 3


def test_kicad_session_busy_board_error_is_actionable(fake_cli: Path) -> None:
    cfg = KiCadMCPConfig(kicad_cli=fake_cli, ipc_retries=1)

    class FakeClient:
        def get_board(self) -> str:
            raise RuntimeError("KiCad is busy and cannot respond to API requests right now")

    session = KiCadSession(
        client_factory=lambda **_kwargs: FakeClient(),
        config_factory=lambda: cfg,
        sleep=lambda _seconds: None,
    )

    with pytest.raises(KiCadBoardNotOpenError, match="busy or modal"):
        session.board()


def test_connection_error_keeps_backward_compatible_message() -> None:
    error = connection._connection_error(KiCadNotRunningError(""))

    assert isinstance(error, connection.KiCadConnectionError)
    assert "Could not connect to KiCad IPC API." in str(error)
    assert "KICAD_MCP_KICAD_SOCKET_PATH" in str(error)


def test_connection_get_kicad_uses_session(monkeypatch: pytest.MonkeyPatch) -> None:
    client = object()

    class FakeSession:
        def client(self) -> object:
            return client

    monkeypatch.setattr(connection, "_session", FakeSession())
    monkeypatch.setattr(connection, "_kicad", None)

    assert connection.get_kicad() is client
    assert connection._kicad is client


def test_connection_get_kicad_preserves_connection_error(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeSession:
        def client(self) -> object:
            raise connection.KiCadConnectionError("already mapped")

    monkeypatch.setattr(connection, "_kicad", None)
    monkeypatch.setattr(connection, "_session", FakeSession())

    with pytest.raises(connection.KiCadConnectionError, match="already mapped"):
        connection.get_kicad()


def test_connection_get_kicad_maps_session_error(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeSession:
        def client(self) -> object:
            raise KiCadMcpError("session failed")

    monkeypatch.setattr(connection, "_kicad", None)
    monkeypatch.setattr(connection, "_session", FakeSession())

    with pytest.raises(connection.KiCadConnectionError, match="session failed"):
        connection.get_kicad()


def test_connection_get_board_maps_board_not_open(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeSession:
        def board(self) -> object:
            raise KiCadBoardNotOpenError("no board")

    monkeypatch.setattr(connection, "_session", FakeSession())

    with pytest.raises(connection.KiCadConnectionError, match="no PCB is open"):
        connection.get_board()


def test_connection_get_board_preserves_busy_message(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeSession:
        def board(self) -> object:
            raise KiCadBoardNotOpenError("KiCad GUI appears to be busy or modal.")

    monkeypatch.setattr(connection, "_session", FakeSession())

    with pytest.raises(connection.KiCadConnectionError, match="busy or modal"):
        connection.get_board()


def test_connection_get_board_preserves_connection_error(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeSession:
        def board(self) -> object:
            raise connection.KiCadConnectionError("mapped board error")

    monkeypatch.setattr(connection, "_session", FakeSession())

    with pytest.raises(connection.KiCadConnectionError, match="mapped board error"):
        connection.get_board()


def test_connection_get_board_maps_session_error(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeSession:
        def board(self) -> object:
            raise KiCadMcpError("board session failed")

    monkeypatch.setattr(connection, "_session", FakeSession())

    with pytest.raises(connection.KiCadConnectionError, match="board session failed"):
        connection.get_board()


def test_reset_connection_closes_cached_client(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    class FakeClient:
        def close(self) -> None:
            calls.append("client_closed")

    class FakeSession:
        def reset(self) -> None:
            calls.append("session_reset")

    monkeypatch.setattr(connection, "_kicad", FakeClient())
    monkeypatch.setattr(connection, "_session", FakeSession())

    connection.reset_connection()

    assert calls == ["client_closed", "session_reset"]
    assert connection._kicad is None
    assert connection._session is None


def test_kicad_session_probe_reports_version(fake_cli: Path) -> None:
    cfg = KiCadMCPConfig(kicad_cli=fake_cli, ipc_retries=0)

    class FakeClient:
        def get_version(self) -> str:
            return "KiCad 10.0.2"

    session = KiCadSession(client_factory=FakeClient, config_factory=lambda: cfg)

    assert session.probe() == {"connected": True, "version": "KiCad 10.0.2"}


def test_kicad_session_probe_handles_clients_without_version(fake_cli: Path) -> None:
    cfg = KiCadMCPConfig(kicad_cli=fake_cli, ipc_retries=0)

    class FakeClient:
        pass

    session = KiCadSession(client_factory=FakeClient, config_factory=lambda: cfg)

    assert session.probe() == {"connected": True, "version": None}


def test_kicad_session_board_requires_get_board(fake_cli: Path) -> None:
    cfg = KiCadMCPConfig(kicad_cli=fake_cli, ipc_retries=0)

    class FakeClient:
        pass

    session = KiCadSession(client_factory=FakeClient, config_factory=lambda: cfg)

    with pytest.raises(KiCadBoardNotOpenError, match="does not expose get_board"):
        session.board()

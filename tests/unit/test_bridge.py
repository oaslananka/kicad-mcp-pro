"""Unit tests for the hybrid bridge daemon (bridge.py)."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from kicad_mcp.bridge import (
    BridgeState,
    _bridge_pid_path,
    _bridge_server,
    _generate_pairing_code,
    _message_too_large_error,
    _proxy_to_local,
    _rate_limited_error,
    _route_message,
    _start_daemon,
    bridge_start,
    bridge_status,
    bridge_stop,
)


def test_bridge_pid_path() -> None:
    """Test that PID path resolves correctly on different platforms."""
    path = _bridge_pid_path()
    assert isinstance(path, Path)
    assert path.name == "bridge.pid"


@patch("kicad_mcp.bridge._bridge_pid_path")
def test_bridge_status_not_running(
    mock_pid_path: MagicMock, capsys: pytest.CaptureFixture[str]
) -> None:
    """Test status command when the bridge is not running."""
    mock_path = MagicMock(spec=Path)
    mock_path.exists.return_value = False
    mock_pid_path.return_value = mock_path

    bridge_status()
    captured = capsys.readouterr()
    assert "Bridge is not running." in captured.out


@patch("kicad_mcp.bridge._bridge_pid_path")
@patch("socket.socket")
def test_bridge_status_running(
    mock_socket: MagicMock, mock_pid_path: MagicMock, capsys: pytest.CaptureFixture[str]
) -> None:
    """Test status command when the bridge is running and responding."""
    mock_path = MagicMock(spec=Path)
    mock_path.exists.return_value = True
    mock_path.read_text.return_value = "1234"
    mock_pid_path.return_value = mock_path

    # Simulate successful socket connection
    mock_s = MagicMock()
    mock_socket.return_value = mock_s

    bridge_status()
    captured = capsys.readouterr()
    assert "Bridge is running" in captured.out
    assert "PID: 1234" in captured.out


@patch("kicad_mcp.bridge._bridge_pid_path")
@patch("socket.socket")
def test_bridge_status_stale_pid(
    mock_socket: MagicMock, mock_pid_path: MagicMock, capsys: pytest.CaptureFixture[str]
) -> None:
    """Test status command when PID file exists but socket fails."""
    mock_path = MagicMock(spec=Path)
    mock_path.exists.return_value = True
    mock_path.read_text.return_value = "1234"
    mock_pid_path.return_value = mock_path

    # Simulate socket connection failure
    mock_socket.return_value.connect.side_effect = ConnectionRefusedError()

    bridge_status()
    captured = capsys.readouterr()
    assert "PID file exists (1234) but bridge is not responding." in captured.out


@patch("kicad_mcp.bridge._bridge_pid_path")
def test_bridge_stop_not_running(
    mock_pid_path: MagicMock, capsys: pytest.CaptureFixture[str]
) -> None:
    """Test stop command when the bridge is not running."""
    mock_path = MagicMock(spec=Path)
    mock_path.exists.return_value = False
    mock_pid_path.return_value = mock_path

    bridge_stop()
    captured = capsys.readouterr()
    assert "Bridge is not running." in captured.out


@patch("kicad_mcp.bridge._bridge_pid_path")
@patch("os.kill")
def test_bridge_stop_success(
    mock_kill: MagicMock, mock_pid_path: MagicMock, capsys: pytest.CaptureFixture[str]
) -> None:
    """Test successful stop command."""
    mock_path = MagicMock(spec=Path)
    mock_path.exists.return_value = True
    mock_path.read_text.return_value = "1234"
    mock_pid_path.return_value = mock_path

    bridge_stop()
    mock_kill.assert_called_once_with(1234, 15)  # SIGTERM = 15
    mock_path.unlink.assert_called_once()
    captured = capsys.readouterr()
    assert "Bridge (PID: 1234) stopped." in captured.out


@patch("kicad_mcp.bridge._bridge_pid_path")
@patch("os.kill")
def test_bridge_stop_process_not_found(
    mock_kill: MagicMock, mock_pid_path: MagicMock, capsys: pytest.CaptureFixture[str]
) -> None:
    """Test stop command when process PID no longer exists (cleanup)."""
    mock_path = MagicMock(spec=Path)
    mock_path.exists.return_value = True
    mock_path.read_text.return_value = "1234"
    mock_pid_path.return_value = mock_path

    mock_kill.side_effect = ProcessLookupError()

    bridge_stop()
    mock_path.unlink.assert_called_once()
    captured = capsys.readouterr()
    assert "Process 1234 not found. Cleaning up PID file." in captured.out


@patch("kicad_mcp.bridge._bridge_pid_path")
@patch("kicad_mcp.bridge._bridge_server", new_callable=MagicMock)
def test_start_daemon_unix(
    mock_bridge_server: MagicMock,
    mock_pid_path: MagicMock,
) -> None:
    """Test Unix fork daemonization path."""
    state = BridgeState(pairing_code="CODE123", port=9090, target_url="http://127.0.0.1:3334")

    mock_path = MagicMock(spec=Path)
    mock_pid_path.return_value = mock_path

    mock_fork = MagicMock()

    # Save original os.fork and temporarily assign our mock
    fork_fn = getattr(os, "fork", None)
    setattr(os, "fork", mock_fork)  # noqa: B010

    try:
        # Test Parent branch (fork returns child PID > 0)
        mock_fork.return_value = 5566
        _start_daemon(state)
        mock_path.write_text.assert_called_once_with("5566")

        # Reset mock
        mock_path.write_text.reset_mock()

        # Test Child branch (fork returns 0)
        mock_fork.return_value = 0
        mock_close = MagicMock()

        with patch.object(sys.stdin, "close", mock_close), patch("asyncio.run") as mock_asyncio_run:
            _start_daemon(state)
            mock_close.assert_called_once()
            mock_bridge_server.assert_called_once_with(state)
            mock_asyncio_run.assert_called_once_with(mock_bridge_server.return_value)
    finally:
        # Restore or remove temporary attribute
        if fork_fn is not None:
            setattr(os, "fork", fork_fn)  # noqa: B010
        else:
            delattr(os, "fork")


@patch("kicad_mcp.bridge._bridge_pid_path")
@patch("subprocess.Popen")
@patch("sys.executable", "python_bin")
def test_start_daemon_windows_fallback(
    mock_popen: MagicMock, mock_pid_path: MagicMock, capsys: pytest.CaptureFixture[str]
) -> None:
    """Test Windows/platform fallback detached process spawn."""
    state = BridgeState(pairing_code="CODE123", port=9090, target_url="http://127.0.0.1:3334")

    mock_path = MagicMock(spec=Path)
    mock_pid_path.return_value = mock_path

    mock_proc = MagicMock()
    mock_proc.pid = 9988
    mock_popen.return_value = mock_proc

    # Temporarily remove os.fork if present to force fallback
    fork_fn = getattr(os, "fork", None)
    if fork_fn is not None:
        delattr(os, "fork")

    try:
        _start_daemon(state)
    finally:
        if fork_fn is not None:
            setattr(os, "fork", fork_fn)  # noqa: B010

    # Verify subprocess was spawned with correct arguments
    mock_popen.assert_called_once()
    args = mock_popen.call_args[0][0]
    assert "python_bin" in args
    assert "bridge" in args
    assert "start" in args
    assert "CODE123" in args

    # Verify PID file was written
    mock_path.write_text.assert_called_once_with("9988")
    captured = capsys.readouterr()
    assert "Bridge daemon started (PID: 9988" in captured.out


@pytest.mark.asyncio
async def test_route_message_ping() -> None:
    """Test routing ping message."""
    state = BridgeState(pairing_code="CODE123", port=9090, target_url="http://127.0.0.1:3334")
    msg = {"jsonrpc": "2.0", "method": "bridge.ping", "id": 42}

    resp = await _route_message(state, msg)
    assert resp is not None
    assert resp["id"] == 42
    assert resp["result"]["pong"] is True


@pytest.mark.asyncio
async def test_route_message_pair_success() -> None:
    """Test successful message pairing."""
    state = BridgeState(pairing_code="CODE123", port=9090, target_url="http://127.0.0.1:3334")
    msg = {"jsonrpc": "2.0", "method": "bridge.pair", "params": {"code": "CODE123"}, "id": 1}

    resp = await _route_message(state, msg)
    assert resp is not None
    assert resp["result"]["status"] == "paired"
    assert state.paired is True
    assert state.paired_at is not None


@pytest.mark.asyncio
async def test_route_message_pair_failure() -> None:
    """Test failed message pairing with wrong code."""
    state = BridgeState(pairing_code="CODE123", port=9090, target_url="http://127.0.0.1:3334")
    msg = {"jsonrpc": "2.0", "method": "bridge.pair", "params": {"code": "WRONG"}, "id": 1}

    resp = await _route_message(state, msg)
    assert resp is not None
    assert "error" in resp
    assert resp["error"]["message"] == "Invalid pairing code"
    assert state.paired is False


@pytest.mark.asyncio
async def test_route_message_unpaired_proxy_denied() -> None:
    """Test that proxy calls are denied when not paired."""
    state = BridgeState(pairing_code="CODE123", port=9090, target_url="http://127.0.0.1:3334")
    msg = {"jsonrpc": "2.0", "method": "pcb_get_tracks", "id": 5}

    resp = await _route_message(state, msg)
    assert resp is not None
    assert resp["error"]["code"] == -32002
    assert "Not paired" in resp["error"]["message"]


@pytest.mark.asyncio
@patch("httpx.AsyncClient.post")
async def test_proxy_to_local_success(mock_post: MagicMock) -> None:
    """Test successful proxy forwarding to local HTTP MCP endpoint."""
    state = BridgeState(
        pairing_code="CODE123",
        port=9090,
        target_url="http://127.0.0.1:3334",
        paired=True,
    )
    msg = {
        "jsonrpc": "2.0",
        "method": "pcb_get_tracks",
        "params": {"board": "demo.kicad_pcb"},
        "id": 9,
    }

    mock_resp = MagicMock()
    mock_resp.json.return_value = {"jsonrpc": "2.0", "id": 1, "result": {"tracks": []}}
    mock_post.return_value = mock_resp

    resp = await _proxy_to_local(state, msg, 9)
    assert resp is not None
    assert resp["id"] == 9
    assert resp["result"]["tracks"] == []


@pytest.mark.asyncio
@patch("httpx.AsyncClient.post")
async def test_proxy_to_local_connection_error(mock_post: MagicMock) -> None:
    """Test proxy error handling when the local server is unreachable."""
    state = BridgeState(
        pairing_code="CODE123",
        port=9090,
        target_url="http://127.0.0.1:3334",
        paired=True,
    )
    msg = {"jsonrpc": "2.0", "method": "pcb_get_tracks", "id": 9}

    import httpx

    mock_post.side_effect = httpx.RequestError("Connection refused")

    resp = await _proxy_to_local(state, msg, 9)
    assert resp is not None
    assert "error" in resp
    assert resp["error"]["code"] == -32003
    assert "Bridge proxy error" in resp["error"]["message"]
    assert state.error_count == 1


def test_generate_pairing_code() -> None:
    code1 = _generate_pairing_code()
    code2 = _generate_pairing_code()
    assert len(code1) == 32
    assert code1.isupper()
    assert int(code1, 16) > 0
    assert code1 != code2


def test_error_helpers() -> None:
    rate_err = _rate_limited_error(123)
    assert rate_err["id"] == 123
    assert rate_err["error"]["code"] == -32004

    large_err = _message_too_large_error(456)
    assert large_err["id"] == 456
    assert large_err["error"]["code"] == -32005


def test_bridge_state_to_dict() -> None:
    state = BridgeState(pairing_code="SECRET_123", port=9090, target_url="http://127.0.0.1:3334")
    public_dict = state.to_dict(include_secret=False)
    assert "pairing_code" not in public_dict
    assert public_dict["port"] == 9090
    assert public_dict["paired"] is False

    private_dict = state.to_dict(include_secret=True)
    assert private_dict["pairing_code"] == "SECRET_123"


def test_bridge_start_flows(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # 1. Daemon branch
    mock_start_daemon = MagicMock()
    monkeypatch.setattr("kicad_mcp.bridge._start_daemon", mock_start_daemon)
    bridge_start(port=9091, code="TESTCODE", daemon=True)
    mock_start_daemon.assert_called_once()
    assert mock_start_daemon.call_args[0][0].port == 9091
    assert mock_start_daemon.call_args[0][0].pairing_code == "TESTCODE"

    # 2. Interactive branch
    mock_start_daemon.reset_mock()
    monkeypatch.setattr("kicad_mcp.setup._check_kicad_mcp_available", lambda: True)

    def mock_run(coro: object) -> None:
        if hasattr(coro, "close"):
            coro.close()

    monkeypatch.setattr("asyncio.run", mock_run)
    bridge_start(port=9092, code="INTERACTIVE")
    captured = capsys.readouterr()
    assert "KiCad MCP Bridge Daemon" in captured.out
    assert "Port:         9092" in captured.out
    assert "Pairing Code: INTERACTIVE" in captured.out


@pytest.mark.asyncio
@patch("httpx.AsyncClient.post")
async def test_proxy_to_local_http_status_error(mock_post: MagicMock) -> None:
    state = BridgeState(
        pairing_code="CODE123",
        port=9090,
        target_url="http://127.0.0.1:3334",
        paired=True,
    )
    msg = {"jsonrpc": "2.0", "method": "pcb_get_tracks", "id": 11}

    import httpx

    mock_resp = MagicMock()
    mock_resp.status_code = 502
    mock_post.side_effect = httpx.HTTPStatusError(
        "Bad Gateway", request=MagicMock(), response=mock_resp
    )

    resp = await _proxy_to_local(state, msg, 11)
    assert resp is not None
    assert "error" in resp
    assert resp["error"]["code"] == -32003
    assert "502" in resp["error"]["message"]
    assert state.error_count == 1


@pytest.mark.asyncio
@patch("httpx.AsyncClient.post")
async def test_proxy_to_local_auth_token_header(
    mock_post: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("KICAD_MCP_AUTH_TOKEN", "bearer_token_xyz")
    state = BridgeState(
        pairing_code="CODE123",
        port=9090,
        target_url="http://127.0.0.1:3334",
        paired=True,
    )
    msg = {"jsonrpc": "2.0", "method": "pcb_get_tracks", "id": 12}

    mock_resp = MagicMock()
    mock_resp.json.return_value = {"jsonrpc": "2.0", "id": 1, "result": {"tracks": []}}
    mock_post.return_value = mock_resp

    await _proxy_to_local(state, msg, 12)
    headers = mock_post.call_args.kwargs.get("headers", {})
    assert headers.get("Authorization") == "Bearer bearer_token_xyz"


@pytest.mark.asyncio
async def test_bridge_server_tcp_lifecycle() -> None:
    import socket

    # Bind to an OS-assigned free port
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    free_port = sock.getsockname()[1]
    sock.close()

    state = BridgeState(
        pairing_code="SECRET_TCP",
        port=free_port,
        target_url="http://127.0.0.1:3334",
    )

    import asyncio

    server_task = asyncio.create_task(_bridge_server(state))
    # Give server a moment to start listening
    await asyncio.sleep(0.1)

    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", free_port)

        # 1. Send invalid JSON
        writer.write(b"not a json string\n")
        await writer.drain()
        await asyncio.sleep(0.05)
        assert state.error_count >= 1

        # 2. Pair successfully
        pair_msg = {
            "jsonrpc": "2.0",
            "method": "bridge.pair",
            "params": {"code": "SECRET_TCP"},
            "id": 1,
        }
        writer.write((json.dumps(pair_msg) + "\n").encode("utf-8"))
        await writer.drain()
        line = await asyncio.wait_for(reader.readline(), timeout=2.0)
        resp = json.loads(line.decode("utf-8"))
        assert resp["result"]["status"] == "paired"
        assert state.paired is True

        # 3. Check status
        status_msg = {"jsonrpc": "2.0", "method": "bridge.status", "id": 2}
        writer.write((json.dumps(status_msg) + "\n").encode("utf-8"))
        await writer.drain()
        line = await asyncio.wait_for(reader.readline(), timeout=2.0)
        resp = json.loads(line.decode("utf-8"))
        assert resp["result"]["port"] == free_port
        assert resp["result"]["paired"] is True

        writer.close()
        await writer.wait_closed()
    finally:
        server_task.cancel()
        await asyncio.gather(server_task, return_exceptions=True)

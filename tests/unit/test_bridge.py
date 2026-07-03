"""Unit tests for the hybrid bridge daemon (bridge.py)."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from kicad_mcp.bridge import (
    BridgeState,
    _bridge_pid_path,
    _proxy_to_local,
    _route_message,
    _start_daemon,
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
@patch("kicad_mcp.bridge._bridge_server")
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
            mock_asyncio_run.assert_called_once()
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

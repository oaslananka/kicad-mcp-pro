"""Regression tests for audit-confirmed security vulnerabilities:
1. CSRF on dashboard mutating routes (KICAD-MCP-WEB-CSRF-TOOL-EXEC)
2. Global pairing reuse in TCP bridge (KICAD-MCP-BRIDGE-GLOBAL-PAIRING-REUSE)
3. SPICE directive newline and command smuggling (KICAD-MCP-SIM-DIRECTIVE-SMUGGLING)
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from kicad_mcp.bridge import (
    BridgeClientSession,
    BridgeState,
    _bridge_server,
    _route_message,
)
from kicad_mcp.config import get_config
from kicad_mcp.server import build_server
from kicad_mcp.tools.simulation import (
    _read_directives,
    _validate_spice_directive,
)

# ===========================================================================
# 1. CSRF Protection on Mutating API Endpoints
# ===========================================================================


def test_origin_validation_blocks_unauthorized_cross_origin_mutations(sample_project: Path) -> None:
    _ = sample_project
    cfg = get_config()
    cfg.transport = "streamable-http"
    cfg.auth_token = ""  # Default unauthenticated state

    server = build_server("minimal")
    client = TestClient(server.streamable_http_app(), raise_server_exceptions=False)

    malicious_headers = {"Origin": "https://malicious-website.com"}

    # 1. Tool execution test endpoint
    resp = client.post(
        "/api/tools/pcb_get_board_summary/test",
        headers=malicious_headers,
        json={},
    )
    assert resp.status_code == 403
    assert "Origin not allowed" in resp.text

    # 2. Server action endpoint (e.g. shutdown / restart)
    resp = client.post(
        "/api/server/shutdown",
        headers=malicious_headers,
        json={},
    )
    assert resp.status_code == 403
    assert "Origin not allowed" in resp.text

    # 3. Config update endpoint
    resp = client.post(
        "/api/config",
        headers=malicious_headers,
        json={"log_level": "DEBUG"},
    )
    assert resp.status_code == 403
    assert "Origin not allowed" in resp.text

    # 4. Same request with legitimate loopback origin is accepted
    loopback_headers = {"Origin": f"http://127.0.0.1:{cfg.port}"}
    resp_loopback = client.post(
        "/api/config",
        headers=loopback_headers,
        json={"log_level": "INFO"},
    )
    assert resp_loopback.status_code != 403


# ===========================================================================
# 2. Bridge Connection Pairing Isolation
# ===========================================================================


@pytest.mark.asyncio
async def test_bridge_pairing_is_scoped_per_connection() -> None:
    """Pairing one connection must not grant paired access to other connections."""
    state = BridgeState(pairing_code="SECRET_KEY_99", port=0, target_url="http://127.0.0.1:3334")

    session1 = BridgeClientSession()
    session2 = BridgeClientSession()

    # Session 1 pairs successfully
    pair_msg = {
        "jsonrpc": "2.0",
        "method": "bridge.pair",
        "params": {"code": "SECRET_KEY_99"},
        "id": 1,
    }
    resp1 = await _route_message(state, pair_msg, session=session1)
    assert resp1 is not None
    assert resp1.get("result", {}).get("status") == "paired"
    assert session1.paired is True

    # Session 2 has not paired; proxy call must be rejected with -32002
    proxy_msg = {"jsonrpc": "2.0", "method": "pcb_get_board_summary", "id": 2}
    resp2 = await _route_message(state, proxy_msg, session=session2)
    assert resp2 is not None
    assert "error" in resp2
    assert resp2["error"]["code"] == -32002
    assert "Not paired" in resp2["error"]["message"]
    assert session2.paired is False

    # Status check for session 2 reports paired=False
    status_msg = {"jsonrpc": "2.0", "method": "bridge.status", "id": 3}
    status_resp = await _route_message(state, status_msg, session=session2)
    assert status_resp is not None
    assert status_resp["result"]["paired"] is False


@pytest.mark.asyncio
async def test_bridge_tcp_server_connection_isolation(unused_tcp_port: int) -> None:
    """E2E TCP test: client 2 cannot access proxied methods without pairing."""
    state = BridgeState(
        pairing_code="TCP_PAIR_SECRET",
        port=unused_tcp_port,
        target_url="http://127.0.0.1:3334",
    )

    server_task = asyncio.create_task(_bridge_server(state))
    await asyncio.sleep(0.05)

    try:
        # Client 1 connects and pairs
        r1, w1 = await asyncio.open_connection("127.0.0.1", unused_tcp_port)
        pair_msg = {
            "jsonrpc": "2.0",
            "method": "bridge.pair",
            "params": {"code": "TCP_PAIR_SECRET"},
            "id": 1,
        }
        w1.write((json.dumps(pair_msg) + "\n").encode("utf-8"))
        await w1.drain()
        line1 = await asyncio.wait_for(r1.readline(), timeout=3.0)
        resp1 = json.loads(line1.decode("utf-8"))
        assert resp1["result"]["status"] == "paired"

        # Client 2 connects concurrently without pairing
        r2, w2 = await asyncio.open_connection("127.0.0.1", unused_tcp_port)
        call_msg = {"jsonrpc": "2.0", "method": "pcb_get_board_summary", "id": 2}
        w2.write((json.dumps(call_msg) + "\n").encode("utf-8"))
        await w2.drain()
        line2 = await asyncio.wait_for(r2.readline(), timeout=3.0)
        resp2 = json.loads(line2.decode("utf-8"))

        # Must be rejected because Client 2 connection is not paired
        assert "error" in resp2
        assert resp2["error"]["code"] == -32002
        assert "Not paired" in resp2["error"]["message"]

        w1.close()
        await w1.wait_closed()
        w2.close()
        await w2.wait_closed()
    finally:
        server_task.cancel()
        await asyncio.gather(server_task, return_exceptions=True)


# ===========================================================================
# 3. SPICE Directive Smuggling Prevention
# ===========================================================================


def test_spice_directive_rejects_newlines_and_control_blocks(sample_project: Path) -> None:
    _ = sample_project

    # 1. Newline injection
    with pytest.raises(ValueError, match="single line without newline characters"):
        _validate_spice_directive(".options nomod\n.control\nshell calc.exe\n.endc")

    with pytest.raises(ValueError, match="single line without newline characters"):
        _validate_spice_directive(".param foo=1\r.control")

    # 2. Control block keywords
    with pytest.raises(ValueError, match="forbidden keyword: .control"):
        _validate_spice_directive(".param val=1 .control")

    with pytest.raises(ValueError, match="forbidden keyword: shell"):
        _validate_spice_directive(".options shell=1")

    # 3. Valid directives pass cleanly
    assert _validate_spice_directive(".param gain=10") == ".param gain=10"
    assert _validate_spice_directive(".options reltol=0.001") == ".options reltol=0.001"
    assert _validate_spice_directive(".tran 1u 10m") == ".tran 1u 10m"


def test_read_directives_filters_tampered_lines(sample_project: Path) -> None:
    cfg = get_config()
    cfg.apply_project(sample_project)
    directive_file = sample_project / ".kicad_mcp_spice_directives.cir"

    # Write a tampered directives file containing injected commands
    directive_file.write_text(
        ".param safe=1\n.control\nshell calc.exe\n.endc\n.options reltol=0.01\n",
        encoding="utf-8",
    )

    directives = _read_directives()
    assert directives == [".param safe=1", ".options reltol=0.01"]
    assert ".control" not in directives
    assert "shell calc.exe" not in directives

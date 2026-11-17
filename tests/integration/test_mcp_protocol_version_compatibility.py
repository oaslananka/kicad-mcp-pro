"""MCP protocol-version compatibility tests.

KiCad MCP Pro advertises both the modern ``2026-07-28`` protocol and the
legacy ``2025-11-25`` protocol (see ``server.json`` and
``src/kicad_mcp/compatibility.py``). The project must not advertise a protocol
version that it does not accept, and must reject clearly unsupported versions.

These tests use raw Streamable HTTP JSON-RPC (not mocked clients) so both
protocol eras are exercised independently: 2026 uses server/discover and 2025
uses initialize. Actual ChatGPT/Claude/Gemini client acceptance is separate.
"""

from __future__ import annotations

import socket
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import httpx
import pytest
import uvicorn
from mcp.server.mcpserver import MCPServer
from starlette.types import ASGIApp

from kicad_mcp.config import get_config
from kicad_mcp.server import build_server

MODERN_PROTOCOL_VERSION = "2026-07-28"
LEGACY_PROTOCOL_VERSION = "2025-11-25"
ADVERTISED_VERSIONS = [MODERN_PROTOCOL_VERSION, LEGACY_PROTOCOL_VERSION]
UNSUPPORTED_PROTOCOL_VERSION = "2020-01-01"
NATIVE_2026_PROTOCOL_LANE = "2026-07-28-rc"

BASE_HEADERS = {
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
}


@contextmanager
def _running_http_server(app: ASGIApp) -> Iterator[str]:
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen(128)
    port = int(listener.getsockname()[1])

    server = uvicorn.Server(
        uvicorn.Config(
            app,
            host="127.0.0.1",
            port=port,
            log_level="error",
            lifespan="on",
        )
    )
    thread = threading.Thread(
        target=server.run,
        kwargs={"sockets": [listener]},
        name="mcp-protocol-version-compat",
        daemon=True,
    )
    thread.start()

    deadline = time.monotonic() + 10.0
    while not server.started and thread.is_alive() and time.monotonic() < deadline:
        time.sleep(0.01)
    if not server.started:
        server.should_exit = True
        thread.join(timeout=2.0)
        listener.close()
        raise RuntimeError("MCP protocol-version compatibility server did not start")

    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=10.0)
        listener.close()
        if thread.is_alive():
            raise RuntimeError("MCP protocol-version compatibility server did not stop")


def _discover_request(client_name: str, protocol_version: str) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "server/discover",
        "params": {
            "_meta": {
                "io.modelcontextprotocol/protocolVersion": protocol_version,
                "io.modelcontextprotocol/clientInfo": {
                    "name": client_name,
                    "version": "smoke",
                },
                "io.modelcontextprotocol/clientCapabilities": {},
            }
        },
    }


def _headers(protocol_version: str, *, method: str = "server/discover") -> dict[str, str]:
    return {
        **BASE_HEADERS,
        "MCP-Protocol-Version": protocol_version,
        "Mcp-Method": method,
    }


def _initialize_request(client_name: str, protocol_version: str) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": protocol_version,
            "capabilities": {},
            "clientInfo": {"name": client_name, "version": "smoke"},
        },
    }


def _configure_server(sample_project: Path, *, protocol_lane: str = "stable") -> MCPServer:
    _ = sample_project
    cfg = get_config()
    cfg.transport = "streamable-http"
    cfg.protocol_lane = protocol_lane
    cfg.stateful_http = False
    cfg.enable_tasks = False
    return build_server("minimal")


@pytest.mark.parametrize("protocol_version", ADVERTISED_VERSIONS)
@pytest.mark.parametrize("client_name", ["chatgpt-connector", "vscode-mcp"])
def test_stable_lane_accepts_advertised_versions(
    sample_project: Path, client_name: str, protocol_version: str
) -> None:
    """Each advertised protocol era must complete its actual connection flow."""
    server = _configure_server(sample_project)

    with _running_http_server(server.streamable_http_app()) as base_url:
        with httpx.Client(base_url=base_url, timeout=10.0) as client:
            if protocol_version == MODERN_PROTOCOL_VERSION:
                result = client.post(
                    "/mcp",
                    headers=_headers(protocol_version),
                    json=_discover_request(client_name, protocol_version),
                )
                assert result.status_code == 200, result.text
                # Modern discovery advertises modern-era versions only.
                assert result.json()["result"]["supportedVersions"] == [MODERN_PROTOCOL_VERSION]
            else:
                result = client.post(
                    "/mcp",
                    headers=_headers(protocol_version, method="initialize"),
                    json=_initialize_request(client_name, protocol_version),
                )
                assert result.status_code == 200, result.text
                assert result.json()["result"]["protocolVersion"] == protocol_version

                tools = client.post(
                    "/mcp",
                    headers=_headers(protocol_version, method="tools/list"),
                    json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
                )
                assert tools.status_code == 200, tools.text
                assert "kicad_get_version" in {
                    tool["name"] for tool in tools.json()["result"]["tools"]
                }

                called = client.post(
                    "/mcp",
                    headers=_headers(protocol_version, method="tools/call"),
                    json={
                        "jsonrpc": "2.0",
                        "id": 3,
                        "method": "tools/call",
                        "params": {"name": "kicad_get_version", "arguments": {}},
                    },
                )
                assert called.status_code == 200, called.text
                assert called.json()["result"]["isError"] is False
                assert "KiCad MCP Pro Server" in called.json()["result"]["content"][0]["text"]


def test_native_2026_lane_rejects_legacy_version(
    sample_project: Path,
) -> None:
    """The native 2026 lane must not accept the legacy 2025-11-25 version."""
    cfg = get_config()
    previous_lane = cfg.protocol_lane
    cfg.protocol_lane = NATIVE_2026_PROTOCOL_LANE
    try:
        server = build_server("minimal")

        with _running_http_server(server.streamable_http_app()) as base_url:
            with httpx.Client(base_url=base_url, timeout=10.0) as client:
                discovered = client.post(
                    "/mcp",
                    headers=_headers(LEGACY_PROTOCOL_VERSION, method="initialize"),
                    json=_initialize_request("chatgpt-connector", LEGACY_PROTOCOL_VERSION),
                )

        assert discovered.status_code == 400, discovered.text
    finally:
        cfg.protocol_lane = previous_lane


def test_unsupported_version_is_rejected(
    sample_project: Path,
) -> None:
    """An unsupported protocol version must fail with a clear error."""
    server = _configure_server(sample_project)

    with _running_http_server(server.streamable_http_app()) as base_url:
        with httpx.Client(base_url=base_url, timeout=10.0) as client:
            discovered = client.post(
                "/mcp",
                headers=_headers(UNSUPPORTED_PROTOCOL_VERSION),
                json=_discover_request("chatgpt-connector", UNSUPPORTED_PROTOCOL_VERSION),
            )

    assert discovered.status_code == 400, discovered.text
    body = discovered.json()
    assert "Unsupported protocol version" in body["error"]["message"]
    assert body["error"]["data"]["requested"] == UNSUPPORTED_PROTOCOL_VERSION
    assert set(ADVERTISED_VERSIONS).issubset(set(body["error"]["data"]["supported"]))

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
from starlette.types import ASGIApp

from kicad_mcp.config import get_config
from kicad_mcp.protocol_compat import CANDIDATE_PROTOCOL_VERSION
from kicad_mcp.server import build_server

BASE_HEADERS = {
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
    "MCP-Protocol-Version": CANDIDATE_PROTOCOL_VERSION,
}


def _request(
    method: str,
    *,
    request_id: int,
    client_name: str,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    request_params = dict(params or {})
    request_params["_meta"] = {
        "io.modelcontextprotocol/protocolVersion": CANDIDATE_PROTOCOL_VERSION,
        "io.modelcontextprotocol/clientInfo": {
            "name": client_name,
            "version": "smoke",
        },
        "io.modelcontextprotocol/clientCapabilities": {},
    }
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": method,
        "params": request_params,
    }


def _headers(method: str, *, name: str | None = None) -> dict[str, str]:
    headers = {**BASE_HEADERS, "Mcp-Method": method}
    if name is not None:
        headers["Mcp-Name"] = name
    return headers


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
        name="mcp-2026-host-smoke",
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
        raise RuntimeError("candidate MCP host-smoke server did not start")

    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=10.0)
        listener.close()
        if thread.is_alive():
            raise RuntimeError("candidate MCP host-smoke server did not stop")


@pytest.mark.parametrize("client_name", ["chatgpt-connector", "vscode-mcp"])
def test_supported_host_profile_smoke_over_real_http(
    sample_project: Path,
    client_name: str,
) -> None:
    _ = sample_project
    cfg = get_config()
    cfg.transport = "streamable-http"
    cfg.protocol_lane = "2026-07-28-rc"
    cfg.stateful_http = False
    cfg.enable_tasks = False
    server = build_server("minimal")

    with _running_http_server(server.streamable_http_app()) as base_url:
        with httpx.Client(base_url=base_url, timeout=10.0) as client:
            discovered = client.post(
                "/mcp",
                headers=_headers("server/discover"),
                json=_request("server/discover", request_id=1, client_name=client_name),
            )
            listed = client.post(
                "/mcp",
                headers=_headers("tools/list"),
                json=_request("tools/list", request_id=2, client_name=client_name),
            )
            called = client.post(
                "/mcp",
                headers=_headers("tools/call", name="kicad_get_version"),
                json=_request(
                    "tools/call",
                    request_id=3,
                    client_name=client_name,
                    params={"name": "kicad_get_version", "arguments": {}},
                ),
            )

    assert discovered.status_code == 200
    assert listed.status_code == 200
    assert called.status_code == 200
    assert "mcp-session-id" not in discovered.headers
    assert "mcp-session-id" not in listed.headers
    assert "mcp-session-id" not in called.headers
    assert discovered.json()["result"]["supportedVersions"] == [CANDIDATE_PROTOCOL_VERSION]
    assert "kicad_get_version" in {tool["name"] for tool in listed.json()["result"]["tools"]}
    assert "KiCad MCP Pro Server" in called.json()["result"]["content"][0]["text"]

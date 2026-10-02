from __future__ import annotations

import secrets
import socket
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import httpx2
import pytest
import uvicorn
from mcp import ClientSession, Implementation, MCPError
from mcp.client.streamable_http import streamable_http_client
from mcp.types.version import LATEST_MODERN_VERSION
from starlette.types import ASGIApp

from kicad_mcp.config import get_config
from kicad_mcp.server import build_server

CANDIDATE_PROTOCOL_VERSION = LATEST_MODERN_VERSION

SUPPORTED_HOST_PROFILES = ("chatgpt-connector", "vscode-mcp")


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
        name="mcp-native-v2-contract",
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
        raise RuntimeError("native MCP v2 contract server did not start")

    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=10.0)
        listener.close()
        if thread.is_alive():
            raise RuntimeError("native MCP v2 contract server did not stop")


def _configure_native_v2_server(sample_project: Path, *, auth_token: str | None = None):
    _ = sample_project
    cfg = get_config()
    cfg.transport = "streamable-http"
    cfg.protocol_lane = "stable"
    cfg.stateful_http = False
    cfg.enable_tasks = False
    cfg.auth_token = auth_token
    return build_server("minimal")


@pytest.mark.parametrize("client_name", SUPPORTED_HOST_PROFILES)
@pytest.mark.asyncio
async def test_sdk_v2_supported_host_profiles_over_real_http(
    sample_project: Path,
    client_name: str,
) -> None:
    server = _configure_native_v2_server(sample_project)
    request_session_ids: list[str] = []
    response_session_ids: list[str] = []

    async def capture_request(request: httpx2.Request) -> None:
        if session_id := request.headers.get("mcp-session-id"):
            request_session_ids.append(session_id)

    async def capture_response(response: httpx2.Response) -> None:
        if session_id := response.headers.get("mcp-session-id"):
            response_session_ids.append(session_id)

    with _running_http_server(server.streamable_http_app()) as base_url:
        async with httpx2.AsyncClient(
            event_hooks={"request": [capture_request], "response": [capture_response]}
        ) as http_client:
            async with streamable_http_client(
                f"{base_url}/mcp",
                http_client=http_client,
            ) as (read_stream, write_stream):
                async with ClientSession(
                    read_stream,
                    write_stream,
                    client_info=Implementation(name=client_name, version="smoke"),
                ) as session:
                    discovered = await session.discover()
                    tools = await session.list_tools()
                    resources = await session.list_resources()
                    prompts = await session.list_prompts()
                    called = await session.call_tool("kicad_get_version", {})
                    missing_tool = await session.call_tool("__native_v2_missing_tool__", {})
                    with pytest.raises(MCPError) as missing_resource:
                        await session.read_resource("kicad://native-v2/missing-resource")

    assert CANDIDATE_PROTOCOL_VERSION in discovered.supported_versions
    assert "kicad_get_version" in {tool.name for tool in tools.tools}
    assert "kicad://board/summary" in {str(resource.uri) for resource in resources.resources}
    assert "first_pcb" in {prompt.name for prompt in prompts.prompts}
    assert called.is_error is False
    assert called.content
    assert any("KiCad MCP Pro Server" in getattr(block, "text", "") for block in called.content)
    assert missing_tool.is_error is True
    assert missing_tool.content
    assert "tool" in missing_tool.content[0].text.lower()
    assert missing_resource.value.code == -32602
    assert "Unknown resource" in missing_resource.value.message
    assert request_session_ids == []
    assert response_session_ids == []


@pytest.mark.parametrize("client_name", SUPPORTED_HOST_PROFILES)
@pytest.mark.asyncio
async def test_sdk_v2_supported_host_profiles_preserve_bearer_authorization(
    sample_project: Path,
    client_name: str,
) -> None:
    token = secrets.token_urlsafe(32)
    server = _configure_native_v2_server(sample_project, auth_token=token)

    discover_headers = {
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
        "MCP-Protocol-Version": CANDIDATE_PROTOCOL_VERSION,
        "Mcp-Method": "server/discover",
    }
    discover_request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "server/discover",
        "params": {
            "_meta": {
                "io.modelcontextprotocol/protocolVersion": CANDIDATE_PROTOCOL_VERSION,
                "io.modelcontextprotocol/clientInfo": {
                    "name": client_name,
                    "version": "smoke",
                },
                "io.modelcontextprotocol/clientCapabilities": {},
            }
        },
    }

    with _running_http_server(server.streamable_http_app()) as base_url:
        async with httpx2.AsyncClient(base_url=base_url) as unauthenticated_client:
            unauthenticated = await unauthenticated_client.post(
                "/mcp",
                headers=discover_headers,
                json=discover_request,
            )

        async with httpx2.AsyncClient(headers={"Authorization": f"Bearer {token}"}) as http_client:
            async with streamable_http_client(
                f"{base_url}/mcp",
                http_client=http_client,
            ) as (read_stream, write_stream):
                async with ClientSession(
                    read_stream,
                    write_stream,
                    client_info=Implementation(name=client_name, version="smoke"),
                ) as session:
                    discovered = await session.discover()
                    tools = await session.list_tools()
                    called = await session.call_tool("kicad_get_version", {})

    assert unauthenticated.status_code == 401
    assert CANDIDATE_PROTOCOL_VERSION in discovered.supported_versions
    assert "kicad_get_version" in {tool.name for tool in tools.tools}
    assert called.is_error is False
    assert called.content
    assert any("KiCad MCP Pro Server" in getattr(block, "text", "") for block in called.content)

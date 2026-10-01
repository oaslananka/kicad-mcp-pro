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
from starlette.types import ASGIApp

from kicad_mcp.config import get_config
from kicad_mcp.protocol_compat import CANDIDATE_PROTOCOL_VERSION
from kicad_mcp.server import build_server


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


@pytest.mark.asyncio
async def test_sdk_v2_native_stateless_surface_over_real_http(sample_project: Path) -> None:
    server = _configure_native_v2_server(sample_project)

    with _running_http_server(server.streamable_http_app()) as base_url:
        async with (
            streamable_http_client(f"{base_url}/mcp") as (read_stream, write_stream),
            ClientSession(
                read_stream,
                write_stream,
                client_info=Implementation(name="kicad-native-v2-contract", version="1.0.0"),
            ) as session,
        ):
            discovered = await session.discover()
            tools = await session.list_tools()
            resources = await session.list_resources()
            prompts = await session.list_prompts()
            missing = await session.call_tool("__native_v2_missing_tool__", {})

    assert CANDIDATE_PROTOCOL_VERSION in discovered.supported_versions
    assert "kicad_get_version" in {tool.name for tool in tools.tools}
    assert "kicad://board/summary" in {str(resource.uri) for resource in resources.resources}
    assert "first_pcb" in {prompt.name for prompt in prompts.prompts}
    assert missing.is_error is True
    assert missing.content
    assert "tool" in missing.content[0].text.lower()


@pytest.mark.asyncio
async def test_sdk_v2_native_discovery_preserves_bearer_authorization(sample_project: Path) -> None:
    token = secrets.token_urlsafe(32)
    server = _configure_native_v2_server(sample_project, auth_token=token)

    with _running_http_server(server.streamable_http_app()) as base_url:
        with pytest.raises(MCPError):
            async with (
                streamable_http_client(f"{base_url}/mcp") as (read_stream, write_stream),
                ClientSession(read_stream, write_stream) as session,
            ):
                await session.discover()

        async with httpx2.AsyncClient(
            headers={"Authorization": f"Bearer {token}"}
        ) as http_client:
            async with (
                streamable_http_client(
                    f"{base_url}/mcp",
                    http_client=http_client,
                ) as (read_stream, write_stream),
                ClientSession(read_stream, write_stream) as session,
            ):
                discovered = await session.discover()
                tools = await session.list_tools()

    assert CANDIDATE_PROTOCOL_VERSION in discovered.supported_versions
    assert "kicad_get_version" in {tool.name for tool in tools.tools}

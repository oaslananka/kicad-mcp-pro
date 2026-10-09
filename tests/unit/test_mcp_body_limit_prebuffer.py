"""Bound MCP HTTP bodies before protocol middleware buffering, including chunked bodies."""

from __future__ import annotations

import pytest
from starlette.testclient import TestClient
from starlette.types import Receive, Scope, Send

from kicad_mcp.config import get_config
from kicad_mcp.server import (
    _McpPostBodyLimitMiddleware,
    _StreamableHttpContractMiddleware,
    build_server,
)


@pytest.mark.parametrize("chunked", [False, True])
def test_oversize_mcp_body_is_rejected_before_contract_buffering(
    sample_project, chunked: bool
) -> None:
    _ = sample_project
    cfg = get_config()
    cfg.transport = "streamable-http"
    app = build_server("minimal").streamable_http_app(max_request_body_size=64)
    body = b"X" * 65
    with TestClient(app, base_url="http://127.0.0.1:3334") as client:
        if chunked:
            response = client.post(
                "/mcp",
                content=(body[:32], body[32:]),
                headers={"Content-Type": "application/json"},
            )
        else:
            response = client.post("/mcp", content=body)
    assert response.status_code == 413
    assert "too large" in response.text.lower()


@pytest.mark.anyio
async def test_http_body_limit_scopes_only_mcp_post_to_preserve_other_routes() -> None:
    recorded: list[str] = []

    async def fake_app(scope: Scope, receive: Receive, send: Send) -> None:
        recorded.append(str(scope.get("path")))
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    app = _McpPostBodyLimitMiddleware(fake_app, max_body_size=2)
    for path in ("/api/example", "/ui", "/mcp"):
        status: list[int] = []

        async def receive():
            return {"type": "http.request", "body": b"123", "more_body": False}

        async def send(message, statuses=status):
            if message["type"] == "http.response.start":
                statuses.append(message["status"])

        await app({"type": "http", "method": "POST", "path": path, "headers": []}, receive, send)
        assert status == [413 if path == "/mcp" else 200]
    assert recorded == ["/api/example", "/ui"]


@pytest.mark.anyio
async def test_invalid_bearer_does_not_trigger_protocol_body_buffer(monkeypatch) -> None:
    cfg = get_config()
    monkeypatch.setattr(cfg, "auth_token", "a" * 32)
    dispatched = False

    async def downstream(scope: Scope, receive: Receive, send: Send) -> None:
        nonlocal dispatched
        dispatched = True

    async def fail_receive():
        raise AssertionError("middleware read unauthorized request body")

    async def send(_message):
        pass

    app = _StreamableHttpContractMiddleware(downstream)
    await app(
        {"type": "http", "path": cfg.mount_path, "method": "POST", "headers": []},
        fail_receive,
        send,
    )
    assert dispatched

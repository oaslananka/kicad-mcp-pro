from __future__ import annotations

import secrets
from pathlib import Path
from typing import Any

from starlette.testclient import TestClient

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
    request_id: int = 1,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    request_params = dict(params or {})
    request_params["_meta"] = {
        "io.modelcontextprotocol/protocolVersion": CANDIDATE_PROTOCOL_VERSION,
        "io.modelcontextprotocol/clientInfo": {
            "name": "mcp-2026-contract-test",
            "version": "1.0.0",
        },
        "io.modelcontextprotocol/clientCapabilities": {},
    }
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": method,
        "params": request_params,
    }


def _headers(method: str, *, name: str | None = None, token: str | None = None) -> dict[str, str]:
    headers = {**BASE_HEADERS, "Mcp-Method": method}
    if name is not None:
        headers["Mcp-Name"] = name
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _candidate_server(sample_project: Path, *, auth_token: str | None = None):
    _ = sample_project
    cfg = get_config()
    cfg.transport = "streamable-http"
    cfg.protocol_lane = "2026-07-28-rc"
    cfg.stateful_http = False
    cfg.enable_tasks = False
    cfg.auth_token = auth_token
    return build_server("minimal")


def test_candidate_discovery_is_available_without_initialize(sample_project: Path) -> None:
    server = _candidate_server(sample_project)

    with TestClient(server.streamable_http_app(), base_url="http://127.0.0.1:3334") as client:
        response = client.post(
            "/mcp",
            headers=_headers("server/discover"),
            json=_request("server/discover"),
        )

    assert response.status_code == 200
    assert "mcp-session-id" not in response.headers
    result = response.json()["result"]
    assert result["resultType"] == "complete"
    assert result["supportedVersions"] == [CANDIDATE_PROTOCOL_VERSION]
    assert result["capabilities"]["extensions"] == {}
    assert result["_meta"]["io.modelcontextprotocol/serverInfo"]["name"] == "kicad-mcp-pro"
    assert result["cacheScope"] == "private"


def test_candidate_tools_list_is_direct_stateless_and_cache_annotated(
    sample_project: Path,
) -> None:
    server = _candidate_server(sample_project)

    with TestClient(server.streamable_http_app(), base_url="http://127.0.0.1:3334") as client:
        response = client.post(
            "/mcp",
            headers=_headers("tools/list"),
            json=_request("tools/list", request_id=2),
        )

    assert response.status_code == 200
    assert "mcp-session-id" not in response.headers
    result = response.json()["result"]
    names = [tool["name"] for tool in result["tools"]]
    assert names == sorted(names)
    assert "kicad_get_version" in names
    assert result["resultType"] == "complete"
    assert result["ttlMs"] == 300_000
    assert result["cacheScope"] == "private"


def test_candidate_tool_call_is_direct_and_has_server_metadata(sample_project: Path) -> None:
    server = _candidate_server(sample_project)

    with TestClient(server.streamable_http_app(), base_url="http://127.0.0.1:3334") as client:
        response = client.post(
            "/mcp",
            headers=_headers("tools/call", name="kicad_get_version"),
            json=_request(
                "tools/call",
                request_id=3,
                params={"name": "kicad_get_version", "arguments": {}},
            ),
        )

    assert response.status_code == 200
    result = response.json()["result"]
    assert result["resultType"] == "complete"
    assert result["_meta"]["io.modelcontextprotocol/serverInfo"]["name"] == "kicad-mcp-pro"
    assert "KiCad MCP Pro Server" in result["content"][0]["text"]


def test_candidate_rejects_legacy_session_header(sample_project: Path) -> None:
    server = _candidate_server(sample_project)
    headers = _headers("tools/list")
    headers["Mcp-Session-Id"] = "legacy-session"

    with TestClient(server.streamable_http_app(), base_url="http://127.0.0.1:3334") as client:
        response = client.post("/mcp", headers=headers, json=_request("tools/list", request_id=4))

    assert response.status_code == 400
    assert response.json()["error"]["code"] == -32020
    assert "Mcp-Session-Id" in response.json()["error"]["message"]


def test_candidate_rejects_legacy_initialize(sample_project: Path) -> None:
    server = _candidate_server(sample_project)

    with TestClient(server.streamable_http_app(), base_url="http://127.0.0.1:3334") as client:
        response = client.post(
            "/mcp",
            headers=_headers("initialize"),
            json=_request("initialize", request_id=5),
        )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == -32601


def test_candidate_requires_method_header(sample_project: Path) -> None:
    server = _candidate_server(sample_project)

    with TestClient(server.streamable_http_app(), base_url="http://127.0.0.1:3334") as client:
        response = client.post(
            "/mcp", headers=BASE_HEADERS, json=_request("tools/list", request_id=6)
        )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == -32020


def test_candidate_preserves_authentication_failure_before_protocol_diagnostics(
    sample_project: Path,
) -> None:
    token = secrets.token_urlsafe(32)
    server = _candidate_server(sample_project, auth_token=token)
    invalid_request = _request("tools/list", request_id=7)
    del invalid_request["params"]["_meta"]["io.modelcontextprotocol/clientCapabilities"]

    with TestClient(server.streamable_http_app(), base_url="http://127.0.0.1:3334") as client:
        unauthenticated = client.post(
            "/mcp",
            headers=_headers("tools/list"),
            json=invalid_request,
        )
        authenticated = client.post(
            "/mcp",
            headers=_headers("tools/list", token=token),
            json=invalid_request,
        )

    assert unauthenticated.status_code == 401
    assert authenticated.status_code == 400
    assert authenticated.json()["error"]["code"] == -32021

from __future__ import annotations

import secrets
from pathlib import Path
from typing import Any

import pytest
from mcp.types.version import LATEST_MODERN_VERSION
from starlette.testclient import TestClient

from kicad_mcp.compatibility import MCP_LEGACY_PROTOCOL_VERSION, MCP_PROTOCOL_VERSION
from kicad_mcp.config import get_config, reset_config
from kicad_mcp.server import build_server

CANDIDATE_PROTOCOL_VERSION = LATEST_MODERN_VERSION

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
    client_name: str = "mcp-2026-contract-test",
) -> dict[str, Any]:
    request_params = dict(params or {})
    request_params["_meta"] = {
        "io.modelcontextprotocol/protocolVersion": CANDIDATE_PROTOCOL_VERSION,
        "io.modelcontextprotocol/clientInfo": {
            "name": client_name,
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
    assert "extensions" not in result["capabilities"]
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
    assert all(isinstance(tool["inputSchema"], dict) for tool in result["tools"])
    assert all(tool["inputSchema"].get("type") == "object" for tool in result["tools"])


def test_candidate_rejects_invalid_json_rpc_envelope(sample_project: Path) -> None:
    server = _candidate_server(sample_project)
    request = _request("tools/list", request_id=8)
    request["jsonrpc"] = "1.0"

    with TestClient(server.streamable_http_app(), base_url="http://127.0.0.1:3334") as client:
        response = client.post("/mcp", headers=_headers("tools/list"), json=request)

    assert response.status_code == 400
    assert response.json()["error"]["code"] == -32600


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


def test_candidate_ignores_legacy_session_header_without_creating_session(
    sample_project: Path,
) -> None:
    server = _candidate_server(sample_project)
    headers = _headers("tools/list")
    headers["Mcp-Session-Id"] = "legacy-session"

    with TestClient(server.streamable_http_app(), base_url="http://127.0.0.1:3334") as client:
        response = client.post("/mcp", headers=headers, json=_request("tools/list", request_id=4))

    assert response.status_code == 200
    assert "mcp-session-id" not in response.headers


def test_candidate_rejects_legacy_initialize(sample_project: Path) -> None:
    server = _candidate_server(sample_project)

    with TestClient(server.streamable_http_app(), base_url="http://127.0.0.1:3334") as client:
        response = client.post(
            "/mcp",
            headers=_headers("initialize"),
            json=_request("initialize", request_id=5),
        )

    assert response.status_code == 404
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
    assert authenticated.json()["error"]["code"] == -32602


def test_candidate_lane_rollback_restores_native_stable_runtime_and_metadata(
    sample_project: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ = sample_project
    monkeypatch.setenv("KICAD_MCP_TRANSPORT", "streamable-http")
    monkeypatch.setenv("KICAD_MCP_PROTOCOL_LANE", "2026-07-28-rc")
    monkeypatch.setenv("KICAD_MCP_STATEFUL_HTTP", "0")
    reset_config()

    candidate_config = get_config()
    assert candidate_config.protocol_lane == "2026-07-28-rc"
    candidate_server = build_server("minimal")

    with TestClient(
        candidate_server.streamable_http_app(),
        base_url="http://127.0.0.1:3334",
    ) as client:
        candidate_initialize = client.post(
            "/mcp",
            headers=_headers("initialize"),
            json=_request("initialize", request_id=20, client_name="rollback-contract"),
        )

    assert candidate_initialize.status_code == 404
    assert candidate_initialize.json()["error"]["code"] == -32601

    monkeypatch.delenv("KICAD_MCP_PROTOCOL_LANE")
    reset_config()

    stable_config = get_config()
    assert stable_config.protocol_lane == "stable"
    stable_server = build_server("minimal")
    initialize_request = {
        "jsonrpc": "2.0",
        "id": 21,
        "method": "initialize",
        "params": {
            "protocolVersion": MCP_LEGACY_PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "rollback-contract", "version": "1.0.0"},
        },
    }
    stable_headers = {
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
    }

    with TestClient(
        stable_server.streamable_http_app(),
        base_url="http://127.0.0.1:3334",
    ) as client:
        initialized = client.post("/mcp", headers=stable_headers, json=initialize_request)
        metadata = client.get("/.well-known/mcp-server")
        discovered = client.post(
            "/mcp",
            headers=_headers("server/discover"),
            json=_request("server/discover", request_id=22, client_name="rollback-contract"),
        )

    assert initialized.status_code == 200
    assert initialized.json()["result"]["protocolVersion"] == MCP_LEGACY_PROTOCOL_VERSION
    assert metadata.status_code == 200
    assert metadata.json()["protocolVersion"] == MCP_PROTOCOL_VERSION
    assert discovered.status_code == 200
    assert CANDIDATE_PROTOCOL_VERSION in discovered.json()["result"]["supportedVersions"]

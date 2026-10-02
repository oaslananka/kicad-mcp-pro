from __future__ import annotations

from pathlib import Path

from mcp.server.caching import CacheHint
from starlette.testclient import TestClient

from kicad_mcp.config import get_config
from kicad_mcp.server import build_server

MODERN_VERSION = "2026-07-28"
BASE_HEADERS = {
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
    "MCP-Protocol-Version": MODERN_VERSION,
}


def _request(method: str, *, request_id: int = 1) -> dict[str, object]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": method,
        "params": {
            "_meta": {
                "io.modelcontextprotocol/protocolVersion": MODERN_VERSION,
                "io.modelcontextprotocol/clientInfo": {
                    "name": "native-2026-bridge-disposition",
                    "version": "1.0.0",
                },
                "io.modelcontextprotocol/clientCapabilities": {},
            }
        },
    }


def _native_candidate_server(sample_project: Path):
    _ = sample_project
    cfg = get_config()
    cfg.transport = "streamable-http"
    cfg.protocol_lane = "2026-07-28-rc"
    cfg.stateful_http = False
    cfg.enable_tasks = False
    return build_server("minimal")


def test_native_sdk_owns_final_2026_discovery_shape(sample_project: Path) -> None:
    server = _native_candidate_server(sample_project)

    with TestClient(server.streamable_http_app(), base_url="http://127.0.0.1:3334") as client:
        response = client.post(
            "/mcp",
            headers={**BASE_HEADERS, "Mcp-Method": "server/discover"},
            json=_request("server/discover"),
        )

    assert response.status_code == 200
    result = response.json()["result"]
    assert result["supportedVersions"] == [MODERN_VERSION]
    assert result["capabilities"]["tools"]["listChanged"] is True
    assert result["capabilities"]["resources"]["subscribe"] is True
    assert "extensions" not in result["capabilities"]


def test_native_candidate_lane_remains_stateless_without_rejecting_legacy_header(
    sample_project: Path,
) -> None:
    server = _native_candidate_server(sample_project)
    headers = {
        **BASE_HEADERS,
        "Mcp-Method": "tools/list",
        "Mcp-Session-Id": "ignored-final-protocol-header",
    }

    with TestClient(server.streamable_http_app(), base_url="http://127.0.0.1:3334") as client:
        response = client.post(
            "/mcp",
            headers=headers,
            json=_request("tools/list", request_id=2),
        )

    assert response.status_code == 200
    assert "mcp-session-id" not in response.headers
    result = response.json()["result"]
    assert result["ttlMs"] == 300_000
    assert result["cacheScope"] == "private"
    names = [tool["name"] for tool in result["tools"]]
    assert names == sorted(names)


def test_native_cache_hints_preserve_reviewed_repository_policy(sample_project: Path) -> None:
    server = _native_candidate_server(sample_project)

    assert server._lowlevel_server.cache_hints == {
        "server/discover": CacheHint(ttl_ms=3_600_000, scope="private"),
        "tools/list": CacheHint(ttl_ms=300_000, scope="private"),
        "prompts/list": CacheHint(ttl_ms=300_000, scope="private"),
        "resources/list": CacheHint(ttl_ms=300_000, scope="private"),
        "resources/templates/list": CacheHint(ttl_ms=300_000, scope="private"),
        "resources/read": CacheHint(ttl_ms=60_000, scope="private"),
    }

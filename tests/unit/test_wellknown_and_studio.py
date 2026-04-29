from __future__ import annotations

import json

import pytest
from starlette.testclient import TestClient

from kicad_mcp.config import get_config
from kicad_mcp.server import build_server, create_server
from kicad_mcp.wellknown import get_wellknown_metadata
from tests.conftest import call_tool_text


def test_wellknown_metadata_matches_server_card_shape() -> None:
    metadata = get_wellknown_metadata()
    assert metadata["$schema"].endswith("/mcp-server-card/v1.json")
    assert metadata["serverInfo"]["name"] == "kicad-mcp-pro"
    assert metadata["capabilities"]["sampling"] is True
    assert "full" in metadata["profiles"]


def test_wellknown_routes_return_identical_payload(monkeypatch, sample_project) -> None:
    _ = sample_project
    monkeypatch.setenv("KICAD_MCP_TRANSPORT", "http")
    monkeypatch.setenv("KICAD_MCP_HOST", "127.0.0.1")
    monkeypatch.setenv("KICAD_MCP_PORT", "3334")
    server = build_server("full")
    client = TestClient(server.streamable_http_app())

    dotted = client.get("/.well-known/mcp-server")
    compat = client.get("/well-known/mcp-server")

    assert dotted.status_code == 200
    assert compat.status_code == 200
    assert dotted.json() == compat.json()
    assert dotted.json()["transport"]["endpoint"] == "http://127.0.0.1:3334/mcp"


def test_streamable_http_legacy_sse_routes_are_opt_in(sample_project) -> None:
    _ = sample_project
    cfg = get_config()
    cfg.transport = "streamable-http"
    cfg.legacy_sse = False

    default_paths = {
        getattr(route, "path", None)
        for route in build_server("minimal").streamable_http_app().routes
    }
    assert "/mcp" in default_paths
    assert "/sse" not in default_paths
    assert "/messages" not in default_paths

    cfg.legacy_sse = True
    legacy_paths = {
        getattr(route, "path", None)
        for route in build_server("minimal").streamable_http_app().routes
    }

    assert "/mcp" in legacy_paths
    assert "/sse" in legacy_paths
    assert "/messages" in legacy_paths


def test_metrics_route_is_opt_in(monkeypatch, sample_project) -> None:
    _ = sample_project
    monkeypatch.setenv("KICAD_MCP_TRANSPORT", "http")
    monkeypatch.setenv("KICAD_MCP_ENABLE_METRICS", "true")
    server = build_server("full")
    client = TestClient(server.streamable_http_app())

    response = client.get("/metrics")

    assert response.status_code == 200
    assert "kicad_mcp_tool_calls_total" in response.text
    assert "kicad_mcp_active_sessions" in response.text


@pytest.mark.anyio
async def test_studio_push_context_updates_resource_and_auto_sets_project(sample_project) -> None:
    server = create_server()
    active_file = sample_project / "demo.kicad_pro"

    result = await call_tool_text(
        server,
        "studio_push_context",
        {
            "active_file": str(active_file),
            "file_type": "other",
            "drc_errors": ["clearance"],
            "selected_reference": "U1",
        },
    )

    resource_items = list(await server.read_resource("kicad://studio/context"))
    payload = json.loads(resource_items[0].content)
    assert payload["active_file"] == str(active_file)
    assert payload["selected_reference"] == "U1"
    assert get_config().project_dir == sample_project.resolve()
    assert "Studio context updated" in result

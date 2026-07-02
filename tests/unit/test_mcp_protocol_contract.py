from __future__ import annotations

from pathlib import Path

from starlette.testclient import TestClient
from starlette.types import Receive, Scope, Send

from kicad_mcp.compatibility import MCP_PROTOCOL_VERSION
from kicad_mcp.config import get_config
from kicad_mcp.server import _StreamableHttpContractMiddleware, build_server

HTTP_HEADERS = {
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
    "MCP-Protocol-Version": MCP_PROTOCOL_VERSION,
}


def _headers(*, session_id: str | None = None) -> dict[str, str]:
    headers = dict(HTTP_HEADERS)
    if session_id:
        headers["MCP-Session-Id"] = session_id
    return headers


def _initialize_request() -> dict[str, object]:
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": MCP_PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "mcp-contract-test", "version": "1.0.0"},
        },
    }


def _initialized_notification() -> dict[str, object]:
    return {"jsonrpc": "2.0", "method": "notifications/initialized"}


def _tools_list_request(request_id: int = 2) -> dict[str, object]:
    return {"jsonrpc": "2.0", "id": request_id, "method": "tools/list", "params": {}}


def _tool_call_request(request_id: int = 3) -> dict[str, object]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "tools/call",
        "params": {"name": "kicad_get_version", "arguments": {}},
    }


def _assert_json_rpc_error(
    response,
    *,
    status_code: int,
    code: int,
    message: str,
    request_id: object | None,
) -> None:
    assert response.status_code == status_code
    assert response.headers["content-type"].startswith("application/json")
    payload = response.json()
    assert payload["jsonrpc"] == "2.0"
    assert payload["id"] == request_id
    assert payload["error"]["code"] == code
    assert payload["error"]["message"] == message


def test_oaslana_71_chatgpt_connector_stateless_tools_list_does_not_require_session_header(
    sample_project: Path,
) -> None:
    """Regression coverage for GitHub issue #34 and OASLANA-71."""
    _ = sample_project
    cfg = get_config()
    cfg.transport = "streamable-http"
    cfg.stateful_http = False
    server = build_server("minimal")

    with TestClient(server.streamable_http_app(), base_url="http://127.0.0.1:3334") as client:
        initialized = client.post("/mcp", headers=_headers(), json=_initialize_request())
        listed = client.post("/mcp", headers=_headers(), json=_tools_list_request())

    assert initialized.status_code == 200
    assert "mcp-session-id" not in initialized.headers
    assert listed.status_code == 200
    tool_names = {tool["name"] for tool in listed.json()["result"]["tools"]}
    assert "kicad_get_version" in tool_names


def test_oaslana_71_custom_mount_path_routes_only_configured_mcp_endpoint(
    sample_project: Path,
) -> None:
    _ = sample_project
    cfg = get_config()
    cfg.transport = "streamable-http"
    cfg.mount_path = "/custom-mcp"
    server = build_server("minimal")

    with TestClient(server.streamable_http_app(), base_url="http://127.0.0.1:3334") as client:
        default_path = client.post("/mcp", headers=_headers(), json=_initialize_request())
        custom_path = client.post("/custom-mcp", headers=_headers(), json=_initialize_request())

    assert default_path.status_code == 404
    assert custom_path.status_code == 200
    assert custom_path.json()["result"]["protocolVersion"] == MCP_PROTOCOL_VERSION


def test_oaslana_71_legacy_sse_routes_are_opt_in(sample_project: Path) -> None:
    _ = sample_project
    cfg = get_config()
    cfg.transport = "streamable-http"
    cfg.legacy_sse = False
    without_legacy = build_server("minimal").streamable_http_app()
    without_legacy_paths = {getattr(route, "path", None) for route in without_legacy.routes}

    cfg.legacy_sse = True
    with_legacy = build_server("minimal").streamable_http_app()
    with_legacy_paths = {getattr(route, "path", None) for route in with_legacy.routes}

    assert "/sse" not in without_legacy_paths
    assert "/messages" not in without_legacy_paths
    assert "/sse" in with_legacy_paths
    assert "/messages" in with_legacy_paths


def test_oaslana_71_stateful_initialized_tools_list_and_tool_call_order(
    sample_project: Path,
) -> None:
    _ = sample_project
    cfg = get_config()
    cfg.transport = "streamable-http"
    cfg.stateful_http = True
    server = build_server("minimal")

    with TestClient(server.streamable_http_app(), base_url="http://127.0.0.1:3334") as client:
        initialized = client.post("/mcp", headers=_headers(), json=_initialize_request())
        session_id = initialized.headers.get("mcp-session-id")
        assert session_id
        session_headers = _headers(session_id=session_id)
        ready = client.post("/mcp", headers=session_headers, json=_initialized_notification())
        listed = client.post("/mcp", headers=session_headers, json=_tools_list_request())
        called = client.post("/mcp", headers=session_headers, json=_tool_call_request())

    assert initialized.status_code == 200
    assert initialized.json()["result"]["protocolVersion"] == MCP_PROTOCOL_VERSION
    assert ready.status_code == 202
    assert ready.text == ""
    assert listed.status_code == 200
    tool_names = {tool["name"] for tool in listed.json()["result"]["tools"]}
    assert "kicad_get_version" in tool_names
    assert called.status_code == 200
    payload = called.json()
    assert payload["id"] == 3
    assert payload["result"]["content"][0]["type"] == "text"
    assert "KiCad MCP Pro Server" in payload["result"]["content"][0]["text"]


def test_oaslana_71_vscode_and_generic_clients_share_the_same_http_contract(
    sample_project: Path,
) -> None:
    _ = sample_project
    cfg = get_config()
    cfg.transport = "streamable-http"
    cfg.stateful_http = False
    server = build_server("minimal")

    client_infos = [
        {"name": "vscode-mcp", "version": "1.0.0"},
        {"name": "generic-mcp-client", "version": "1.0.0"},
    ]

    with TestClient(server.streamable_http_app(), base_url="http://127.0.0.1:3334") as client:
        for index, client_info in enumerate(client_infos, start=10):
            request = _initialize_request()
            request["id"] = index
            params = request["params"]
            assert isinstance(params, dict)
            params["clientInfo"] = client_info
            initialized = client.post("/mcp", headers=_headers(), json=request)
            ready = client.post("/mcp", headers=_headers(), json=_initialized_notification())
            listed = client.post("/mcp", headers=_headers(), json=_tools_list_request(index + 10))

            assert initialized.status_code == 200
            assert initialized.json()["result"]["protocolVersion"] == MCP_PROTOCOL_VERSION
            assert ready.status_code == 202
            assert listed.status_code == 200


def test_stateful_session_errors_are_structured_and_spec_aligned(
    sample_project: Path,
) -> None:
    _ = sample_project
    cfg = get_config()
    cfg.transport = "streamable-http"
    cfg.stateful_http = True
    server = build_server("minimal")

    with TestClient(server.streamable_http_app(), base_url="http://127.0.0.1:3334") as client:
        initialized = client.post("/mcp", headers=_headers(), json=_initialize_request())
        session_id = initialized.headers.get("mcp-session-id")
        missing_session = client.post("/mcp", headers=_headers(), json=_tools_list_request())
        invalid_session = client.post(
            "/mcp",
            headers=_headers(session_id="missing-session"),
            json=_tools_list_request(3),
        )
        listed = client.post(
            "/mcp",
            headers=_headers(session_id=str(session_id)),
            json=_tools_list_request(4),
        )

    assert initialized.status_code == 200
    assert session_id
    _assert_json_rpc_error(
        missing_session,
        status_code=400,
        code=-32000,
        message="Bad Request: Missing MCP-Session-Id header.",
        request_id=2,
    )
    _assert_json_rpc_error(
        invalid_session,
        status_code=404,
        code=-32001,
        message="Session not found for MCP-Session-Id.",
        request_id=3,
    )
    assert listed.status_code == 200


def test_streamable_http_logs_initialize_create_and_destroy_lifecycle(
    sample_project: Path,
    monkeypatch,
) -> None:
    _ = sample_project
    cfg = get_config()
    cfg.transport = "streamable-http"
    cfg.stateful_http = True
    server = build_server("minimal")
    events: list[tuple[str, dict[str, object]]] = []
    monkeypatch.setattr(
        "kicad_mcp.server.logger.info",
        lambda event, **kwargs: events.append((event, kwargs)),
    )

    with TestClient(server.streamable_http_app(), base_url="http://127.0.0.1:3334") as client:
        initialized = client.post("/mcp", headers=_headers(), json=_initialize_request())
        session_id = initialized.headers.get("mcp-session-id")
        client.delete("/mcp", headers=_headers(session_id=str(session_id)))

    assert initialized.status_code == 200
    assert session_id
    initialize = [item for item in events if item[0] == "mcp_transport_initialize"]
    created = [item for item in events if item[0] == "mcp_session_created"]
    destroyed = [item for item in events if item[0] == "mcp_session_destroyed"]
    assert initialize
    assert initialize[0][1]["request_id"] == 1
    assert created
    assert created[0][1]["mcp_session_id"] == session_id
    assert destroyed
    assert destroyed[0][1]["mcp_session_id"] == session_id


def test_stateful_malformed_json_rpc_is_not_masked_by_session_check(
    sample_project: Path,
) -> None:
    _ = sample_project
    cfg = get_config()
    cfg.transport = "streamable-http"
    cfg.stateful_http = True
    server = build_server("minimal")

    with TestClient(server.streamable_http_app(), base_url="http://127.0.0.1:3334") as client:
        response = client.post(
            "/mcp",
            headers=_headers(),
            json={"jsonrpc": "2.0", "id": 9, "params": {}},
        )

    payload = response.json()
    assert response.status_code == 400
    assert payload["jsonrpc"] == "2.0"
    assert payload["error"]["code"] != -32000
    assert payload["error"]["message"] != "Bad Request: Missing MCP-Session-Id header."


def test_streamable_http_rejects_unsupported_protocol_version_header(
    sample_project: Path,
) -> None:
    _ = sample_project
    cfg = get_config()
    cfg.transport = "streamable-http"
    server = build_server("minimal")

    with TestClient(server.streamable_http_app(), base_url="http://127.0.0.1:3334") as client:
        response = client.post(
            "/mcp",
            headers={**_headers(), "MCP-Protocol-Version": "1900-01-01"},
            json=_initialize_request(),
        )

    _assert_json_rpc_error(
        response,
        status_code=400,
        code=-32002,
        message=f"Unsupported MCP-Protocol-Version: 1900-01-01. Expected {MCP_PROTOCOL_VERSION}.",
        request_id=1,
    )


def test_streamable_http_requires_json_and_sse_accept_header(sample_project: Path) -> None:
    _ = sample_project
    cfg = get_config()
    cfg.transport = "streamable-http"
    server = build_server("minimal")

    with TestClient(server.streamable_http_app(), base_url="http://127.0.0.1:3334") as client:
        response = client.post(
            "/mcp",
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "MCP-Protocol-Version": MCP_PROTOCOL_VERSION,
            },
            json=_initialize_request(),
        )

    _assert_json_rpc_error(
        response,
        status_code=400,
        code=-32003,
        message="Bad Request: Accept header must include application/json and text/event-stream.",
        request_id=1,
    )


def test_streamable_http_requires_json_content_type(sample_project: Path) -> None:
    _ = sample_project
    cfg = get_config()
    cfg.transport = "streamable-http"
    server = build_server("minimal")

    with TestClient(server.streamable_http_app(), base_url="http://127.0.0.1:3334") as client:
        response = client.post(
            "/mcp",
            headers={
                "Accept": "application/json, text/event-stream",
                "Content-Type": "text/plain",
                "MCP-Protocol-Version": MCP_PROTOCOL_VERSION,
            },
            json=_initialize_request(),
        )

    _assert_json_rpc_error(
        response,
        status_code=400,
        code=-32003,
        message="Bad Request: Content-Type header must be application/json.",
        request_id=1,
    )


def test_streamable_http_accepts_split_accept_headers(sample_project: Path) -> None:
    _ = sample_project
    cfg = get_config()
    cfg.transport = "streamable-http"
    server = build_server("minimal")

    with TestClient(server.streamable_http_app(), base_url="http://127.0.0.1:3334") as client:
        response = client.post(
            "/mcp",
            headers=[
                ("Accept", "application/json"),
                ("Accept", "text/event-stream"),
                ("Content-Type", "application/json"),
                ("MCP-Protocol-Version", MCP_PROTOCOL_VERSION),
            ],
            json=_initialize_request(),
        )

    assert response.status_code == 200


def test_contract_middleware_bounds_remembered_streamable_http_sessions() -> None:
    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        _ = scope, receive, send

    middleware = _StreamableHttpContractMiddleware(app)

    for index in range(257):
        middleware._remember_session(f"session-{index}")

    assert middleware._has_session("session-0") is False
    assert middleware._has_session("session-256") is True
    assert len(middleware._session_ids) == 256

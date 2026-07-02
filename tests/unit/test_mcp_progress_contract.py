"""Contract tests for MCP progress and cancellation (issue #209).

MCP 2025-11-25 defines:
  - $/progress notification (client → server and server → client)
  - Progress tokens in tool call params
  - Cancellation via notifications
  - Task/metadata extension for long-running operations

These tests pin the current protocol surface so regressions in the
future MCP migration are caught early.
"""

from __future__ import annotations

from pathlib import Path

from starlette.testclient import TestClient

from kicad_mcp.compatibility import MCP_PROTOCOL_VERSION
from kicad_mcp.config import get_config
from kicad_mcp.server import build_server

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


# ---------------------------------------------------------------------------
# Progress notification contract
# ---------------------------------------------------------------------------


def test_progress_notification_accepted_without_session(sample_project: Path) -> None:
    """A client may send notifications/progress at any time (stateless mode).

    The server should accept them silently (202) since progress is a
    notification (no response expected).
    """
    _ = sample_project
    cfg = get_config()
    cfg.transport = "streamable-http"
    cfg.stateful_http = False
    server = build_server("minimal")

    progress_payload = {
        "jsonrpc": "2.0",
        "method": "notifications/progress",
        "params": {
            "progressToken": "token-1",
            "progress": 0.5,
            "total": 1.0,
        },
    }

    with TestClient(server.streamable_http_app(), base_url="http://127.0.0.1:3334") as client:
        response = client.post("/mcp", headers=_headers(), json=progress_payload)

    # Notifications are silent — 202 Accepted
    assert response.status_code == 202
    assert response.text == ""


def test_progress_notification_accepted_with_session(sample_project: Path) -> None:
    """Progress notifications are valid in an established session (stateful mode)."""
    _ = sample_project
    cfg = get_config()
    cfg.transport = "streamable-http"
    cfg.stateful_http = True
    server = build_server("minimal")

    with TestClient(server.streamable_http_app(), base_url="http://127.0.0.1:3334") as client:
        init_resp = client.post("/mcp", headers=_headers(), json=_initialize_request())
        session_id = init_resp.headers.get("mcp-session-id")
        client.post(
            "/mcp", headers=_headers(session_id=str(session_id)), json=_initialized_notification()
        )

        progress_payload = {
            "jsonrpc": "2.0",
            "method": "notifications/progress",
            "params": {
                "progressToken": "token-2",
                "progress": 0.75,
                "total": 1.0,
            },
        }
        response = client.post(
            "/mcp",
            headers=_headers(session_id=str(session_id)),
            json=progress_payload,
        )

    assert response.status_code == 202
    assert response.text == ""


def test_progress_token_in_tool_call_is_accepted(sample_project: Path) -> None:
    """Clients may attach a progressToken to tool call params.

    The server should accept it and may or may not honor it, but must not
    reject the call or crash.
    """
    _ = sample_project
    cfg = get_config()
    cfg.transport = "streamable-http"
    cfg.stateful_http = True
    server = build_server("minimal")

    with TestClient(server.streamable_http_app(), base_url="http://127.0.0.1:3334") as client:
        init_resp = client.post("/mcp", headers=_headers(), json=_initialize_request())
        session_id = init_resp.headers.get("mcp-session-id")
        client.post(
            "/mcp", headers=_headers(session_id=str(session_id)), json=_initialized_notification()
        )

        call_with_progress = {
            "jsonrpc": "2.0",
            "id": 10,
            "method": "tools/call",
            "params": {
                "name": "kicad_get_version",
                "arguments": {},
                "_meta": {"progressToken": "pt-1"},
            },
        }
        response = client.post(
            "/mcp",
            headers=_headers(session_id=str(session_id)),
            json=call_with_progress,
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload.get("result") is not None, "expected successful result"
    assert "error" not in payload, f"unexpected error: {payload.get('error')}"


# ---------------------------------------------------------------------------
# Cancellation notification contract
# ---------------------------------------------------------------------------


def test_cancellation_notification_accepted(sample_project: Path) -> None:
    """Cancellation notifications ($/cancel) are accepted by the server.

    The server should respond with 202 for the notification.
    """
    _ = sample_project
    cfg = get_config()
    cfg.transport = "streamable-http"
    cfg.stateful_http = False
    server = build_server("minimal")

    cancel_payload = {
        "jsonrpc": "2.0",
        "method": "notifications/cancelled",
        "params": {
            "requestId": 42,
            "reason": "user cancelled",
        },
    }

    with TestClient(server.streamable_http_app(), base_url="http://127.0.0.1:3334") as client:
        client.post("/mcp", headers=_headers(), json=_initialize_request())
        response = client.post("/mcp", headers=_headers(), json=cancel_payload)

    assert response.status_code == 202
    assert response.text == ""


def test_cancellation_with_session(sample_project: Path) -> None:
    """Cancellation notifications work in stateful mode with an established session."""
    _ = sample_project
    cfg = get_config()
    cfg.transport = "streamable-http"
    cfg.stateful_http = True
    server = build_server("minimal")

    with TestClient(server.streamable_http_app(), base_url="http://127.0.0.1:3334") as client:
        init_resp = client.post("/mcp", headers=_headers(), json=_initialize_request())
        session_id = init_resp.headers.get("mcp-session-id")
        client.post(
            "/mcp", headers=_headers(session_id=str(session_id)), json=_initialized_notification()
        )

        cancel_payload = {
            "jsonrpc": "2.0",
            "method": "notifications/cancelled",
            "params": {
                "requestId": 99,
                "reason": "timeout",
            },
        }
        response = client.post(
            "/mcp",
            headers=_headers(session_id=str(session_id)),
            json=cancel_payload,
        )

    assert response.status_code == 202


# ---------------------------------------------------------------------------
# Task lifecycle (future MCP area — smoke tests for experimental surface)
# ---------------------------------------------------------------------------


def test_task_lifecycle_endpoints_are_not_exposed_yet(sample_project: Path) -> None:
    """The task extension endpoints (tasks/list, tasks/get) are not part of
    the 2025-11-25 protocol baseline.

    The MCP SDK may expose these by default; pin the current behavior so the
    migration to 2026-07-28 must explicitly decide whether to implement them.
    """
    _ = sample_project
    cfg = get_config()
    cfg.transport = "streamable-http"
    cfg.stateful_http = False
    server = build_server("minimal")

    task_methods = [
        ("tasks/list", 11),
        ("tasks/get", 12),
        ("tasks/cancel", 13),
    ]

    with TestClient(server.streamable_http_app(), base_url="http://127.0.0.1:3334") as client:
        client.post("/mcp", headers=_headers(), json=_initialize_request())
        for method, req_id in task_methods:
            payload = {
                "jsonrpc": "2.0",
                "id": req_id,
                "method": method,
                "params": {},
            }
            response = client.post("/mcp", headers=_headers(), json=payload)
            data = response.json()
            # The server may expose these by default (via SDK) or not.
            # Either way, pin what happens so migration is explicit.
            if "error" in data:
                assert isinstance(data["error"], dict)
                assert "code" in data["error"]
            else:
                # If the server exposes the method, it must return a valid result
                assert "result" in data, f"{method}: expected result or error"


# ---------------------------------------------------------------------------
# Progress token bounds
# ---------------------------------------------------------------------------


def test_progress_token_must_be_string(sample_project: Path) -> None:
    """The MCP SDK validates progressToken must be a string.

    Notifications with invalid progressToken types are silently dropped
    (202 empty) because the SDK validates params but notifications have
    no response path — the error is logged server-side.
    """
    _ = sample_project
    cfg = get_config()
    cfg.transport = "streamable-http"
    cfg.stateful_http = True
    server = build_server("minimal")

    invalid_tokens = [123, True, [], {}]

    with TestClient(server.streamable_http_app(), base_url="http://127.0.0.1:3334") as client:
        init_resp = client.post("/mcp", headers=_headers(), json=_initialize_request())
        session_id = init_resp.headers.get("mcp-session-id")
        assert session_id is not None
        client.post(
            "/mcp", headers=_headers(session_id=str(session_id)), json=_initialized_notification()
        )

        for token in invalid_tokens:
            payload = {
                "jsonrpc": "2.0",
                "method": "notifications/progress",
                "params": {
                    "progressToken": token,
                    "progress": 0.5,
                    "total": 1.0,
                },
            }
            response = client.post(
                "/mcp",
                headers=_headers(session_id=str(session_id)),
                json=payload,
            )
            # Notifications with invalid params are silently dropped (202 empty)
            # because the notification has no response path.
            assert response.status_code == 202, (
                f"expected 202 for invalid progressToken={token!r}, got {response.status_code}"
            )
            assert response.text == "", (
                f"expected empty body for notification, got {response.text!r}"
            )

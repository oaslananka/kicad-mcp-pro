"""Bridge daemon rate-limiting (work order P5-T5, threat model K8).

The bridge previously processed unbounded inbound messages, leaving the 24-bit
pairing code open to brute force and the proxy open to floods. These tests pin the
token-bucket budget and the pairing throttle.
"""

from __future__ import annotations

import asyncio

import httpx

from kicad_mcp.bridge import (
    BRIDGE_MAX_MESSAGE_BYTES,
    BRIDGE_MESSAGE_TOO_LARGE_ERROR_CODE,
    RATE_LIMIT_ERROR_CODE,
    BridgeState,
    TokenBucket,
    _message_too_large_error,
    _proxy_to_local,
    _route_message,
)


class _Clock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t

    def advance(self, delta: float) -> None:
        self.t += delta


def _state(**overrides: object) -> BridgeState:
    state = BridgeState(pairing_code="ABC123", port=9090, target_url="http://127.0.0.1:9090")
    for key, value in overrides.items():
        setattr(state, key, value)
    return state


def test_token_bucket_allows_burst_then_refills() -> None:
    clock = _Clock()
    bucket = TokenBucket(capacity=3, refill_per_second=1.0, time_fn=clock)
    assert [bucket.allow() for _ in range(3)] == [True, True, True]
    assert bucket.allow() is False  # burst exhausted
    clock.advance(2.0)  # refill two tokens
    assert bucket.allow() is True
    assert bucket.allow() is True
    assert bucket.allow() is False


def test_route_message_enforces_general_rate_limit() -> None:
    clock = _Clock()
    state = _state(rate_limiter=TokenBucket(capacity=2, refill_per_second=0.0, time_fn=clock))

    first = asyncio.run(_route_message(state, {"method": "bridge.ping", "id": 1}))
    second = asyncio.run(_route_message(state, {"method": "bridge.ping", "id": 2}))
    blocked = asyncio.run(_route_message(state, {"method": "bridge.ping", "id": 3}))

    assert first is not None and first["result"]["pong"] is True  # type: ignore[index]
    assert second is not None
    assert blocked is not None and blocked["error"]["code"] == RATE_LIMIT_ERROR_CODE  # type: ignore[index]
    assert state.rate_limited_count == 1
    assert state.request_count == 2  # blocked request is not counted as served


def test_pairing_brute_force_is_throttled() -> None:
    clock = _Clock()
    state = _state(
        rate_limiter=TokenBucket(capacity=1000, refill_per_second=0.0, time_fn=clock),
        pair_limiter=TokenBucket(capacity=3, refill_per_second=0.0, time_fn=clock),
    )

    for i in range(3):
        resp = asyncio.run(
            _route_message(state, {"method": "bridge.pair", "id": i, "params": {"code": "WRONG"}})
        )
        assert resp is not None and resp["error"]["message"] == "Invalid pairing code"  # type: ignore[index]

    throttled = asyncio.run(
        _route_message(state, {"method": "bridge.pair", "id": 99, "params": {"code": "WRONG"}})
    )
    assert throttled is not None
    assert throttled["error"]["code"] == RATE_LIMIT_ERROR_CODE  # type: ignore[index]
    assert state.paired is False


def test_bridge_status_does_not_expose_pairing_code() -> None:
    state = _state()

    status = asyncio.run(_route_message(state, {"method": "bridge.status", "id": 7}))

    assert status is not None
    result = status["result"]  # type: ignore[index]
    assert "pairing_code" not in result
    assert state.to_dict(include_secret=True)["pairing_code"] == "ABC123"


def test_proxy_to_local_sends_streamable_http_headers(monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    class _Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {"jsonrpc": "2.0", "result": {"ok": True}}

    class _Client:
        def __init__(self, *, base_url: str, timeout: float) -> None:
            self.base_url = base_url
            self.timeout = timeout

        async def __aenter__(self) -> _Client:
            return self

        async def __aexit__(self, exc_type: object, exc: object, tb: object) -> bool:
            return False

        async def post(
            self,
            path: str,
            *,
            json: dict[str, object],
            headers: dict[str, str],
        ) -> _Response:
            calls.append(
                {"base_url": self.base_url, "path": path, "json": json, "headers": headers}
            )
            return _Response()

    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    monkeypatch.setenv("KICAD_MCP_AUTH_TOKEN", "test-token-with-at-least-32-characters")
    state = _state(target_url="http://127.0.0.1:3334")

    response = asyncio.run(
        _proxy_to_local(state, {"method": "kicad_get_version", "params": {}}, msg_id=42)
    )

    assert response == {"jsonrpc": "2.0", "id": 42, "result": {"ok": True}}
    assert len(calls) == 1
    headers = calls[0]["headers"]
    assert isinstance(headers, dict)
    assert headers["Accept"] == "application/json, text/event-stream"
    assert headers["Content-Type"] == "application/json"
    assert headers["MCP-Protocol-Version"] == "2025-11-25"
    assert headers["Authorization"] == "Bearer test-token-with-at-least-32-characters"
    payload = calls[0]["json"]
    assert isinstance(payload, dict)
    assert payload["method"] == "tools/call"
    assert payload["params"] == {"name": "kicad_get_version", "arguments": {}}


def test_proxy_to_local_preserves_json_rpc_error(monkeypatch) -> None:
    class _Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {"jsonrpc": "2.0", "error": {"code": -32000, "message": "bad call"}}

    class _Client:
        def __init__(self, *, base_url: str, timeout: float) -> None:
            pass

        async def __aenter__(self) -> _Client:
            return self

        async def __aexit__(self, exc_type: object, exc: object, tb: object) -> bool:
            return False

        async def post(
            self,
            path: str,
            *,
            json: dict[str, object],
            headers: dict[str, str],
        ) -> _Response:
            return _Response()

    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    state = _state(target_url="http://127.0.0.1:3334")

    response = asyncio.run(_proxy_to_local(state, {"method": "bad_tool"}, msg_id=5))

    assert response == {"jsonrpc": "2.0", "id": 5, "error": {"code": -32000, "message": "bad call"}}


def test_message_too_large_error_reports_bridge_limit() -> None:
    response = _message_too_large_error()

    assert response["jsonrpc"] == "2.0"
    assert response["id"] is None
    error = response["error"]
    assert isinstance(error, dict)
    assert error["code"] == BRIDGE_MESSAGE_TOO_LARGE_ERROR_CODE
    assert str(BRIDGE_MAX_MESSAGE_BYTES) in str(error["message"])


def test_message_too_large_error_preserves_request_id() -> None:
    response = _message_too_large_error(msg_id="oversize-1")

    assert response["id"] == "oversize-1"
    error = response["error"]
    assert isinstance(error, dict)
    assert error["code"] == BRIDGE_MESSAGE_TOO_LARGE_ERROR_CODE

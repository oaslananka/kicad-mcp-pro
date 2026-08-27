"""Unit tests for KiCadSession TTL caching, retry backoff, and error escalation."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest
from kipy.errors import ApiError
from kipy.proto.common import ApiStatusCode

from kicad_mcp.errors import (
    IpcDisconnectedError,
    KiCadConnectionTimeoutError,
)
from kicad_mcp.kicad.session import KiCadSession, SessionConfig, _classify_ipc_error


@dataclass
class FakeConfig:
    """Minimal SessionConfig for testing."""

    kicad_socket_path: Path | None = None
    kicad_token: str | None = None
    ipc_connection_timeout: float = 10.0
    ipc_retries: int = 2
    ipc_cache_ttl: float = 5.0


class _FakeClient:
    """A stub KiCad IPC client that can track connect/disconnect."""

    def __init__(self, *, fail_count: int = 0) -> None:
        self.fail_count = fail_count
        self._call_count = 0
        self.closed = False

    def close(self) -> None:
        self.closed = True


def _dummy_sleep(_: float) -> None:
    """No-op sleep for deterministic tests."""


def _make_session(
    *,
    client_factory: Callable[..., object] | None = None,
    config: SessionConfig | None = None,
    sleep: Callable[[float], None] = _dummy_sleep,
) -> KiCadSession:
    if client_factory is None:
        client_factory = _FakeClient
    cfg = config or FakeConfig()

    def _config_factory() -> SessionConfig:
        return cfg

    return KiCadSession(
        client_factory=client_factory,
        config_factory=_config_factory,
        sleep=sleep,
    )


# ---------------------------------------------------------------------------
# Basic connect / cached response
# ---------------------------------------------------------------------------


def test_connect_returns_client() -> None:
    session = _make_session()
    client = session.client()
    assert isinstance(client, _FakeClient)
    assert client.closed is False


def test_connect_is_cached_within_ttl() -> None:
    factory_call_count = 0

    def factory() -> _FakeClient:
        nonlocal factory_call_count
        factory_call_count += 1
        return _FakeClient()

    session = _make_session(client_factory=factory)
    c1 = session.client()
    c2 = session.client()
    assert c1 is c2  # same object
    assert factory_call_count == 1


def test_reset_clears_cache() -> None:
    session = _make_session()
    c1 = session.client()
    assert session.continuity_generation == 0
    session.reset()
    assert session.continuity_generation == 1
    c2 = session.client()
    assert c1 is not c2
    assert c1.closed is True  # closed by reset


# ---------------------------------------------------------------------------
# TTL expiry — cache reconnection
# ---------------------------------------------------------------------------


class _MonotonicClock:
    """Simulate time.monotonic() for deterministic TTL tests."""

    def __init__(self, start: float = 0.0) -> None:
        self._now = start

    def advance(self, delta: float) -> None:
        self._now += delta

    def __call__(self) -> float:
        return self._now


class _ContinuityProbeClient(_FakeClient):
    def __init__(self, *, probe: Callable[[], None]) -> None:
        super().__init__()
        self._probe = probe

    def get_version(self) -> str:
        self._probe()
        return "10.0.5"


def test_ttl_expiry_probes_healthy_cached_client_without_breaking_continuity() -> None:
    """TTL freshness checks must not invalidate a still-live KiCad transaction."""
    clock = _MonotonicClock()
    factory_call_count = 0
    probe_count = 0

    def probe() -> None:
        nonlocal probe_count
        probe_count += 1

    def factory() -> _ContinuityProbeClient:
        nonlocal factory_call_count
        factory_call_count += 1
        return _ContinuityProbeClient(probe=probe)

    session = _make_session(client_factory=factory, config=FakeConfig(ipc_cache_ttl=5.0))

    with pytest.MonkeyPatch().context() as mp:
        mp.setattr(time, "monotonic", clock)
        first = session.client()
        clock.advance(6.0)
        second = session.client()

    assert second is first
    assert first.closed is False
    assert factory_call_count == 1
    assert probe_count == 1
    assert session.continuity_generation == 0


def test_ttl_probe_token_mismatch_reconnects_and_breaks_continuity() -> None:
    """A restarted KiCad instance must invalidate the previous transaction epoch."""
    clock = _MonotonicClock()
    factory_call_count = 0

    def factory() -> _ContinuityProbeClient:
        nonlocal factory_call_count
        factory_call_count += 1
        if factory_call_count == 1:
            return _ContinuityProbeClient(
                probe=lambda: (_ for _ in ()).throw(
                    ApiError(
                        "KiCad token mismatch",
                        code=ApiStatusCode.AS_TOKEN_MISMATCH,
                    )
                )
            )
        return _ContinuityProbeClient(probe=lambda: None)

    session = _make_session(client_factory=factory, config=FakeConfig(ipc_cache_ttl=5.0))

    with pytest.MonkeyPatch().context() as mp:
        mp.setattr(time, "monotonic", clock)
        first = session.client()
        clock.advance(6.0)
        second = session.client()

    assert second is not first
    assert first.closed is True
    assert factory_call_count == 2
    assert session.continuity_generation == 1


# ---------------------------------------------------------------------------
# Retry backoff
# ---------------------------------------------------------------------------


def test_retry_success_after_transient_failures() -> None:
    """Factory fails N times then succeeds; retry must recover."""
    attempt_log: list[int] = []

    def factory() -> _FakeClient:
        attempt = len(attempt_log) + 1
        attempt_log.append(attempt)
        if attempt <= 2:  # first 2 calls fail
            raise ConnectionError("KiCad busy")
        return _FakeClient()

    session = _make_session(
        client_factory=factory,
        config=FakeConfig(ipc_retries=3),
    )
    client = session.client()
    assert isinstance(client, _FakeClient)
    assert len(attempt_log) == 3  # fail/fail/succeed


def test_retry_exhaustion_raises_ipc_disconnected() -> None:
    """All retries exhausted → IpcDisconnectedError."""
    attempt_log: list[int] = []

    def factory() -> _FakeClient:
        attempt_log.append(len(attempt_log) + 1)
        raise ConnectionError("KiCad not reachable")

    session = _make_session(
        client_factory=factory,
        config=FakeConfig(ipc_retries=2),
    )

    with pytest.raises(IpcDisconnectedError) as exc_info:
        session.client()

    assert "not reachable after multiple retries" in str(exc_info.value)
    assert exc_info.value.code == "IPC_DISCONNECTED"
    assert exc_info.value.retryable is True
    assert len(attempt_log) == 3  # initial + 2 retries


def test_timeout_error_raises_connection_timeout() -> None:
    """Error with 'timeout' in message → KiCadConnectionTimeoutError."""

    def factory() -> _FakeClient:
        raise TimeoutError("timed out")

    session = _make_session(
        client_factory=factory,
        config=FakeConfig(ipc_retries=1),
    )

    with pytest.raises(KiCadConnectionTimeoutError) as exc_info:
        session.client()

    assert exc_info.value.code == "KICAD_CONNECTION_TIMEOUT"
    assert exc_info.value.retryable is True


# ---------------------------------------------------------------------------
# Exponential backoff values
# ---------------------------------------------------------------------------


def test_backoff_sequence() -> None:
    """Sleep is called with expected exponential backoff durations."""
    sleeps: list[float] = []

    def recording_sleep(duration: float) -> None:
        sleeps.append(duration)

    def factory() -> _FakeClient:
        raise ConnectionError("fail")

    session = _make_session(
        client_factory=factory,
        config=FakeConfig(ipc_retries=3),
        sleep=recording_sleep,
    )

    with pytest.raises(IpcDisconnectedError):
        session.client()

    # Retries=3 → 3 backoff steps: 0.5, 1.0, 2.0 (capped)
    assert sleeps == [0.5, 1.0, 2.0], f"Expected [0.5, 1.0, 2.0] got {sleeps}"


# ---------------------------------------------------------------------------
# reconnect after reset
# ---------------------------------------------------------------------------


def test_reconnect_after_reset() -> None:
    session = _make_session()
    c1 = session.client()
    session.reset()
    c2 = session.client()
    assert c1 is not c2
    assert c1.closed is True
    assert c2.closed is False


# ---------------------------------------------------------------------------
# Structural error classification (P5-T5)
# ---------------------------------------------------------------------------


def test_classify_ipc_error_treats_kicad_token_mismatch_as_disconnect() -> None:
    error = ApiError(
        "request reached another KiCad instance",
        code=ApiStatusCode.AS_TOKEN_MISMATCH,
    )

    assert _classify_ipc_error(error) == "disconnected"


def test_classify_ipc_error_prefers_type_over_message() -> None:
    # Typed failures are classified by type — even when the message says nothing
    # about the failure mode — so a reworded/localized message can't flip them.
    assert _classify_ipc_error(TimeoutError("operation exceeded the deadline")) == "timeout"
    assert _classify_ipc_error(ConnectionResetError("xyz")) == "disconnected"
    assert _classify_ipc_error(BrokenPipeError("xyz")) == "disconnected"
    assert _classify_ipc_error(ConnectionRefusedError()) == "disconnected"
    assert _classify_ipc_error(EOFError()) == "disconnected"


def test_classify_ipc_error_substring_is_only_a_fallback() -> None:
    # Opaque RuntimeErrors (what kipy often raises) fall back to message parsing.
    assert _classify_ipc_error(RuntimeError("Request timed out")) == "timeout"
    assert _classify_ipc_error(RuntimeError("connection reset by peer")) == "disconnected"
    assert _classify_ipc_error(RuntimeError("KiCad is busy with a modal dialog")) == "busy"
    assert _classify_ipc_error(RuntimeError("totally unrelated")) == "other"


# ---------------------------------------------------------------------------
# KiCad-restart / disconnect cache invalidation (P5-T5)
# ---------------------------------------------------------------------------


class _BoardClient:
    """Fake client whose get_board() outcome is scripted per instance."""

    def __init__(self, *, board: object | None, error: Exception | None) -> None:
        self._board = board
        self._error = error
        self.closed = False

    def close(self) -> None:
        self.closed = True

    def get_board(self) -> object:
        if self._error is not None:
            raise self._error
        return self._board


def test_board_disconnect_invalidates_cache_and_reconnects() -> None:
    # A disconnect (KiCad restarted) must drop the cached client and reconnect to
    # the fresh session rather than serving the dead one for the rest of the TTL.
    live_board = object()
    clients: list[_BoardClient] = [
        _BoardClient(board=None, error=ConnectionResetError("peer reset")),
        _BoardClient(board=live_board, error=None),
    ]
    factory_calls = 0

    def factory() -> _BoardClient:
        nonlocal factory_calls
        client = clients[factory_calls]
        factory_calls += 1
        return client

    session = _make_session(client_factory=factory, config=FakeConfig(ipc_retries=2))
    assert session.board() is live_board
    assert factory_calls == 2  # reconnected after the disconnect
    assert clients[0].closed is True  # stale client was closed, not reused
    assert session.continuity_generation == 1


def test_board_disconnect_exhausted_raises_ipc_disconnected() -> None:
    def factory() -> _BoardClient:
        return _BoardClient(board=None, error=BrokenPipeError("pipe gone"))

    session = _make_session(client_factory=factory, config=FakeConfig(ipc_retries=1))
    with pytest.raises(IpcDisconnectedError) as exc_info:
        session.board()
    assert exc_info.value.code == "IPC_DISCONNECTED"

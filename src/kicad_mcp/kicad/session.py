"""Central KiCad IPC session adapter."""

from __future__ import annotations

import inspect
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Literal, Protocol, TypedDict

from kipy.errors import ApiError
from kipy.proto.common import ApiStatusCode

from ..errors import (
    IpcDisconnectedError,
    KiCadBoardNotOpenError,
    KiCadConnectionTimeoutError,
)


class LoggerLike(Protocol):
    """Small logging protocol used to avoid binding to a concrete logger type."""

    def debug(self, event: str, **kwargs: object) -> None:
        """Emit debug information."""

    def warning(self, event: str, **kwargs: object) -> None:
        """Emit warning information."""


class KiCadKwargs(TypedDict, total=False):
    """Keyword arguments supported by known kipy.KiCad constructors."""

    socket_path: str
    kicad_token: str
    client_name: str
    timeout_ms: int


KiCadClientFactory = Callable[..., object]


class SessionConfig(Protocol):
    """Configuration fields used by the session adapter."""

    kicad_socket_path: str | Path | None
    kicad_token: str | None
    ipc_connection_timeout: float
    ipc_retries: int
    ipc_cache_ttl: float


ConfigFactory = Callable[[], SessionConfig]
_BUSY_PATTERNS = (
    "busy",
    "cannot respond",
    "modal",
    "temporarily unavailable",
    "try again",
)


def _default_config() -> SessionConfig:
    from ..config import get_config

    return get_config()


def _is_busy_error(message: str) -> bool:
    lowered = message.casefold()
    return any(pattern in lowered for pattern in _BUSY_PATTERNS)


IpcErrorKind = Literal["timeout", "disconnected", "busy", "other"]

_TIMEOUT_PATTERNS = ("timeout", "timed out", "deadline")
_DISCONNECT_PATTERNS = (
    "disconnect",
    "broken pipe",
    "connection reset",
    "connection refused",
    "connection aborted",
    "not connected",
    "socket closed",
    "eof",
)


def _classify_ipc_error(exc: BaseException) -> IpcErrorKind:
    """Classify an IPC failure by exception *type* first, message only as a fallback.

    Structural exception types (``TimeoutError``, the ``ConnectionError`` family,
    ``EOFError``) are authoritative and translation-stable. Substring matching on the
    message is a last resort for the opaque ``RuntimeError``s kipy raises when it
    cannot surface a typed error — so a localized or reworded message can never flip
    the classification of a genuinely typed failure.
    """
    if isinstance(exc, TimeoutError):
        return "timeout"
    if isinstance(exc, (ConnectionError, EOFError)):
        return "disconnected"
    if isinstance(exc, ApiError) and exc.code == ApiStatusCode.AS_TOKEN_MISMATCH:
        return "disconnected"
    lowered = str(exc).casefold()
    if any(pattern in lowered for pattern in _TIMEOUT_PATTERNS):
        return "timeout"
    if any(pattern in lowered for pattern in _DISCONNECT_PATTERNS):
        return "disconnected"
    if _is_busy_error(lowered):
        return "busy"
    return "other"


class KiCadSession:
    """Thread-safe lazy KiCad IPC session with TTL caching and auto-reconnect."""

    def __init__(
        self,
        *,
        client_factory: KiCadClientFactory,
        config_factory: ConfigFactory = _default_config,
        logger: LoggerLike | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._client_factory = client_factory
        self._config_factory = config_factory
        self._logger = logger
        self._sleep = sleep
        self._lock = threading.RLock()
        self._client: object | None = None
        self._last_connect_time: float = 0.0
        self._continuity_generation = 0

    def _get_ttl(self) -> float:
        """Return the configured IPC cache TTL in seconds."""
        return self._config_factory().ipc_cache_ttl

    @property
    def continuity_generation(self) -> int:
        """Return the generation of continuity-breaking resets/disconnects."""
        with self._lock:
            return self._continuity_generation

    def reset(self) -> None:
        """Close and clear the cached client and invalidate transaction continuity."""
        with self._lock:
            self._close_client()
            self._client = None
            self._last_connect_time = 0.0
            self._continuity_generation += 1

    def _close_client(self) -> None:
        """Safely close the current client connection."""
        if self._client is not None:
            close_fn = getattr(self._client, "close", None)
            if callable(close_fn):
                try:
                    close_fn()
                except Exception as exc:  # pragma: no cover - defensive cleanup
                    if self._logger is not None:
                        self._logger.debug("kicad_close_failed", error=str(exc))

    def _constructor_params(self) -> set[str]:
        signature_target = getattr(self._client_factory, "__init__", self._client_factory)
        try:
            return set(inspect.signature(signature_target).parameters.keys()) - {"self"}
        except (TypeError, ValueError):
            return set()

    def build_kwargs(self) -> KiCadKwargs:
        """Build only the kwargs accepted by the active KiCad client factory."""
        cfg = self._config_factory()
        available = self._constructor_params()
        kwargs: KiCadKwargs = {}

        if "socket_path" in available and cfg.kicad_socket_path is not None:
            kwargs["socket_path"] = str(cfg.kicad_socket_path)
        if "kicad_token" in available and cfg.kicad_token is not None:
            kwargs["kicad_token"] = cfg.kicad_token
        if "client_name" in available:
            kwargs["client_name"] = "kicad-mcp"
        if "timeout_ms" in available:
            kwargs["timeout_ms"] = int(cfg.ipc_connection_timeout * 1000)
        return kwargs

    def _probe_cached_continuity(self) -> bool:
        """Prove the cached client still targets the same KiCad instance.

        KiCad's response token is bound to one running application instance.  The
        kipy client automatically reuses the learned token on later requests, so a
        lightweight request detects a restarted server as ``AS_TOKEN_MISMATCH``.
        Raw tokens are never read, logged, or exposed here.
        """
        client = self._client
        if client is None:
            return False
        get_version = getattr(client, "get_version", None)
        if not callable(get_version):
            self.reset()
            return False
        try:
            get_version()
        except Exception as exc:
            kind = _classify_ipc_error(exc)
            if kind in ("timeout", "disconnected"):
                self.reset()
                return False
            if self._logger is not None:
                self._logger.debug("kicad_continuity_probe_deferred", kind=kind)
        self._last_connect_time = time.monotonic()
        return True

    def client(self) -> object:
        """Return a connected KiCad IPC client with TTL continuity checks.

        Once the cache TTL elapses, probe the existing authenticated KiCad client
        before replacing it.  A healthy same-instance client is retained so native
        transactions can span the TTL.  Timeout, disconnect, or KiCad token mismatch
        invalidates continuity, increments the session generation, and reconnects.
        """
        with self._lock:
            # TTL check — validate continuity before replacing an authenticated client.
            if self._client is not None:
                elapsed = time.monotonic() - self._last_connect_time
                if elapsed > self._get_ttl():
                    if self._logger is not None:
                        self._logger.debug(
                            "kicad_cache_expired",
                            elapsed_seconds=round(elapsed, 2),
                            ttl_seconds=self._get_ttl(),
                        )
                    self._probe_cached_continuity()

            if self._client is None:
                self._client = self._connect_with_retry()

            return self._client

    def _connect_with_retry(self) -> object:
        """Attempt to connect with exponential backoff.

        Attempt 1 is immediate.  Each subsequent retry waits with exponential
        backoff: 0.5s, 1s, 2s (capped at 2s).  Total attempts = ipc_retries + 1.
        Raises ``IpcDisconnectedError`` after all retries are exhausted.
        """
        cfg = self._config_factory()
        kwargs = self.build_kwargs()
        total_attempts = max(1, cfg.ipc_retries + 1)

        # Exponential backoff sequence (used after attempt 1)
        backoff_times = [min(0.5 * (2**i), 2.0) for i in range(cfg.ipc_retries)]

        last_error: BaseException | None = None
        for attempt in range(1, total_attempts + 1):
            # Sleep *before* every attempt except the first
            if attempt > 1 and backoff_times:
                self._sleep(backoff_times[attempt - 2])
            if self._logger is not None:
                self._logger.debug(
                    "kicad_connect",
                    attempt=attempt,
                    max_attempts=total_attempts,
                    kwargs=list(kwargs.keys()),
                )
            try:
                client = self._client_factory(**kwargs)
                self._last_connect_time = time.monotonic()
                return client
            except Exception as exc:
                last_error = exc
                if self._logger is not None:
                    self._logger.warning(
                        "kicad_connect_failed",
                        attempt=attempt,
                        max_attempts=total_attempts,
                        error=str(exc),
                        socket_path=str(cfg.kicad_socket_path) if cfg.kicad_socket_path else None,
                    )

        if last_error is not None and _classify_ipc_error(last_error) == "timeout":
            raise KiCadConnectionTimeoutError(
                "Could not connect to KiCad IPC API before the configured timeout."
            ) from last_error
        raise IpcDisconnectedError(
            "KiCad IPC API server is not reachable after multiple retries. "
            "Make sure KiCad is running and the IPC API server is enabled."
        ) from last_error

    def board(self) -> object:
        """Return the active KiCad board.

        Re-acquires the client on every attempt so that a connection dropped by a
        KiCad restart invalidates the TTL cache immediately: on a disconnect-class
        failure the stale client is closed and the next attempt reconnects to the
        live session instead of serving a dead one (the TTL alone could keep a
        post-restart stale client for several seconds).
        """
        cfg = self._config_factory()
        attempts = max(1, cfg.ipc_retries + 1)
        last_error: BaseException | None = None

        for attempt in range(1, attempts + 1):
            client = self.client()  # reconnects if the cache was invalidated
            get_board = getattr(client, "get_board", None)
            if not callable(get_board):
                raise KiCadBoardNotOpenError("KiCad client does not expose get_board().")
            try:
                return get_board()
            except Exception as exc:
                last_error = exc
                kind = _classify_ipc_error(exc)
                if self._logger is not None:
                    self._logger.warning(
                        "kicad_get_board_failed",
                        attempt=attempt,
                        attempts=attempts,
                        error=str(exc),
                        kind=kind,
                    )
                if kind == "disconnected":
                    # KiCad went away or restarted — drop the stale client so the
                    # next attempt reconnects rather than reusing a dead session.
                    self.reset()
                if kind in ("busy", "disconnected") and attempt < attempts:
                    self._sleep(min(0.2 * attempt, 1.0))
                    continue
                break

        kind = _classify_ipc_error(last_error) if last_error is not None else "other"
        if kind == "disconnected":
            raise IpcDisconnectedError(
                "The KiCad IPC connection dropped (KiCad may have closed or restarted) "
                "and did not recover. Reopen the board in KiCad and retry."
            ) from last_error
        if kind == "busy":
            raise KiCadBoardNotOpenError(
                "KiCad GUI appears to be busy or modal and cannot respond to IPC requests "
                "right now. Try again, close any open KiCad dialog, or finish/save the "
                "current GUI operation before retrying."
            ) from last_error
        raise KiCadBoardNotOpenError(
            "KiCad IPC is reachable, but no PCB is open in the active KiCad session."
        ) from last_error

    def probe(self) -> dict[str, object]:
        """Return a small capability probe without leaking secrets."""
        client = self.client()
        get_version = getattr(client, "get_version", None)
        version = get_version() if callable(get_version) else None
        return {"connected": True, "version": version}

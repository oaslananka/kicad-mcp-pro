"""Thread-safe KiCad IPC connection management."""

from __future__ import annotations

import inspect
import threading
from collections.abc import Generator
from contextlib import contextmanager
from typing import TypedDict

import structlog
from kipy.board import Board
from kipy.kicad import KiCad

from .config import get_config


class KiCadConnectionError(RuntimeError):
    """Raised when KiCad IPC connection fails."""


logger = structlog.get_logger(__name__)
_lock = threading.Lock()
_kicad: KiCad | None = None


class _KiCadKwargs(TypedDict, total=False):
    socket_path: str
    kicad_token: str
    client_name: str
    timeout_ms: int


def _build_kicad_kwargs() -> _KiCadKwargs:
    """Build only the kwargs that kipy.KiCad.__init__ actually accepts.

    kipy's constructor signature varies by version. We inspect it at runtime
    so we never pass unknown keyword arguments that would raise TypeError.
    Supported params (kipy 0.5.x): socket_path, client_name, kicad_token, timeout_ms
    """
    cfg = get_config()
    available = set(inspect.signature(KiCad.__init__).parameters.keys()) - {"self"}
    kwargs: _KiCadKwargs = {}

    if "socket_path" in available and cfg.kicad_socket_path is not None:
        kwargs["socket_path"] = str(cfg.kicad_socket_path)

    if "kicad_token" in available and cfg.kicad_token is not None:
        kwargs["kicad_token"] = cfg.kicad_token

    if "client_name" in available:
        kwargs["client_name"] = "kicad-mcp"

    if "timeout_ms" in available:
        kwargs["timeout_ms"] = int(cfg.ipc_connection_timeout * 1000)

    return kwargs


def get_kicad() -> KiCad:
    """Return a thread-safe KiCad IPC connection."""
    global _kicad
    with _lock:
        if _kicad is None:
            kwargs = _build_kicad_kwargs()
            logger.debug("kicad_connect", kwargs=list(kwargs.keys()))
            try:
                _kicad = KiCad(**kwargs)
            except Exception as exc:
                raise KiCadConnectionError(
                    "Could not connect to KiCad IPC API.\n"
                    "Make sure KiCad is running and the IPC API is enabled:\n"
                    "  KiCad → Preferences → Scripting → Enable IPC API Server"
                ) from exc
    return _kicad


def get_board() -> Board:
    """Return the active board from KiCad."""
    try:
        return get_kicad().get_board()
    except Exception as exc:
        raise KiCadConnectionError("KiCad is connected but no board is currently open.") from exc


def reset_connection() -> None:
    """Force reconnect on next use."""
    global _kicad
    with _lock:
        if _kicad is not None:
            try:
                close_fn = getattr(_kicad, "close", None)
                if callable(close_fn):
                    close_fn()
            except Exception as exc:
                logger.debug("kicad_close_failed", error=str(exc))
        _kicad = None


@contextmanager
def board_transaction() -> Generator[Board, None, None]:
    """Context manager for board operations."""
    board = get_board()
    try:
        yield board
    except KiCadConnectionError:
        reset_connection()
        raise

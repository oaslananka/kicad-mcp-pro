"""Thread-safe KiCad IPC connection management."""

from __future__ import annotations

import threading
from collections.abc import Generator
from contextlib import contextmanager
from typing import cast

import structlog
from kipy.board import Board
from kipy.kicad import KiCad

from .config import get_config
from .errors import KiCadBoardNotOpenError, KiCadMcpError, KiCadNotRunningError
from .kicad.session import KiCadSession


class KiCadConnectionError(KiCadNotRunningError):
    """Raised when KiCad IPC connection fails."""


logger = structlog.get_logger(__name__)
_lock = threading.RLock()
_session: KiCadSession | None = None
_kicad: object | None = None
_connection_generation = 0


def _get_session() -> KiCadSession:
    """Return the process-wide KiCad session adapter."""
    global _session
    with _lock:
        if _session is None:
            _session = KiCadSession(client_factory=KiCad, logger=logger)
        return _session


def _connection_error(exc: KiCadMcpError) -> KiCadConnectionError:
    return KiCadConnectionError(
        str(exc)
        or (
            "Could not connect to KiCad IPC API.\n"
            "Make sure KiCad is running and the IPC API is enabled:\n"
            "  KiCad -> Preferences -> Scripting -> Enable IPC API Server\n"
            "If you use a custom socket or token, set:\n"
            "  KICAD_MCP_KICAD_SOCKET_PATH\n"
            "  KICAD_MCP_KICAD_TOKEN"
        )
    )


def get_kicad() -> KiCad:
    """Return a thread-safe KiCad IPC connection."""
    global _kicad
    _ = get_config()
    try:
        _kicad = _get_session().client()
        return cast(KiCad, _kicad)
    except KiCadConnectionError:
        raise
    except KiCadMcpError as exc:
        raise _connection_error(exc) from exc


def get_board() -> Board:
    """Return the active board from KiCad."""
    try:
        return cast(Board, _get_session().board())
    except KiCadConnectionError:
        raise
    except KiCadBoardNotOpenError as exc:
        logger.debug("kicad_get_board_failed", error=str(exc))
        message = str(exc)
        if "busy" not in message.casefold():
            message = (
                "KiCad IPC is reachable, but no PCB is open in the active KiCad session.\n"
                "Open a .kicad_pcb file in KiCad or call kicad_set_project() to point the "
                "server at the expected project files."
            )
        raise KiCadConnectionError(message) from exc
    except KiCadMcpError as exc:
        raise _connection_error(exc) from exc


def get_connection_epoch() -> tuple[int, int]:
    """Return an internal epoch that changes after explicit reset or IPC disconnect."""
    with _lock:
        session_generation = _session.continuity_generation if _session is not None else -1
        return (_connection_generation, session_generation)


def reset_connection() -> None:
    """Force reconnect on next use."""
    global _session, _kicad, _connection_generation
    with _lock:
        _connection_generation += 1
        if _kicad is not None:
            close_fn = getattr(_kicad, "close", None)
            if callable(close_fn):
                try:
                    close_fn()
                except Exception as exc:
                    logger.debug("kicad_close_failed", error=str(exc))
        if _session is not None:
            _session.reset()
        _session = None
        _kicad = None


@contextmanager
def board_transaction() -> Generator[Board]:
    """Context manager for board operations."""
    with _lock:
        board = get_board()
        try:
            yield board
        except KiCadConnectionError:
            reset_connection()
            raise

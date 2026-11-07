"""Shared mutable state between server.py and web routes.

Centralises metrics, server handle, and start-time references so that
both the MCP server and the HTTP dashboard API endpoints share the same
in-memory state without circular imports.
"""

from __future__ import annotations

import secrets
import threading
import time
from collections import deque
from typing import Any

_METRICS_LOCK: threading.Lock = threading.Lock()
_TOOL_CALL_COUNTS: dict[tuple[str, str], int] = {}
_TOOL_LATENCIES_MS: dict[str, deque[float]] = {}
_server_start_time: float = time.time()
_server_handle: Any = None


def set_server_handle(handle: Any) -> None:  # noqa: ANN401
    """Store a reference to the active MCP server for tool discovery."""
    global _server_handle
    _server_handle = handle


def get_server_handle() -> Any:  # noqa: ANN401
    """Return the stored server handle (``_SyncServerHandle`` or ``KiCadFastMCP``)."""
    return _server_handle


def reset_start_time() -> None:
    """Reset the server start time (e.g. after a restart)."""
    global _server_start_time
    _server_start_time = time.time()


def get_start_time() -> float:
    """Return the monotonic server start timestamp."""
    return _server_start_time


def get_metrics_snapshot() -> dict[str, object]:
    """Return a JSON-safe snapshot of all tool metrics.

    Safe to call from any thread.
    """
    with _METRICS_LOCK:
        call_counts: dict[str, dict[str, int]] = {}
        for (tool, status), count in _TOOL_CALL_COUNTS.items():
            tool_entry = call_counts.setdefault(tool, {})
            tool_entry[status] = tool_entry.get(status, 0) + count

        latencies: dict[str, object] = {}
        for tool, samples in _TOOL_LATENCIES_MS.items():
            ordered = sorted(samples)
            latencies[tool] = {
                "count": len(samples),
                "p50": _percentile_from_sorted(ordered, 0.50),
                "p95": _percentile_from_sorted(ordered, 0.95),
                "p99": _percentile_from_sorted(ordered, 0.99),
                "min": ordered[0] if ordered else 0.0,
                "max": ordered[-1] if ordered else 0.0,
            }

    return {
        "call_counts": call_counts,
        "latencies_ms": latencies,
        "total_calls": sum(t.get("ok", 0) + t.get("error", 0) for t in call_counts.values()),
        "total_errors": sum(t.get("error", 0) for t in call_counts.values()),
    }


def reset_metrics() -> None:
    """Clear all tool call counters and latency samples.

    Used by tests to prevent cross-test pollution of module-level state.
    """
    global _TOOL_CALL_COUNTS, _TOOL_LATENCIES_MS  # noqa: PLW0603
    with _METRICS_LOCK:
        _TOOL_CALL_COUNTS.clear()
        _TOOL_LATENCIES_MS.clear()


def _percentile_from_sorted(ordered: list[float], percentile: float) -> float:
    if not ordered:
        return 0.0
    index = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * percentile))))
    return ordered[index]


# Desktop update gate. This is process-local and is enforced at the main
# MCP call boundary, not only at the HTTP dashboard route.
_MAINTENANCE_LOCK = threading.RLock()
_ACTIVE_MCP_CALLS = 0
_MAINTENANCE_OWNER: str | None = None
_MAINTENANCE_TOKEN: str | None = None


def reserve_tool_execution() -> bool:
    """Atomically reject new tool executions during a reviewed update."""
    global _ACTIVE_MCP_CALLS
    with _MAINTENANCE_LOCK:
        if _MAINTENANCE_OWNER is not None:
            return False
        _ACTIVE_MCP_CALLS += 1
        return True


def finish_tool_execution() -> None:
    """Release one previously accepted tool invocation."""
    global _ACTIVE_MCP_CALLS
    with _MAINTENANCE_LOCK:
        if _ACTIVE_MCP_CALLS <= 0:
            raise RuntimeError("Unbalanced MCP tool execution")
        _ACTIVE_MCP_CALLS -= 1


def begin_maintenance(owner_session: str) -> str | None:
    """Quiesce only when no MCP call is active; never interrupt a tool."""
    global _MAINTENANCE_OWNER, _MAINTENANCE_TOKEN
    with _MAINTENANCE_LOCK:
        if _ACTIVE_MCP_CALLS != 0 or _MAINTENANCE_OWNER is not None:
            return None
        token = secrets.token_urlsafe(32)
        _MAINTENANCE_OWNER = owner_session
        _MAINTENANCE_TOKEN = token
        return token


def end_maintenance(owner_session: str, token: str) -> bool:
    """Re-enable calls only for the original owner and one-time token."""
    global _MAINTENANCE_OWNER, _MAINTENANCE_TOKEN
    with _MAINTENANCE_LOCK:
        if (
            not _MAINTENANCE_TOKEN
            or _MAINTENANCE_OWNER != owner_session
            or not secrets.compare_digest(_MAINTENANCE_TOKEN, token)
        ):
            return False
        _MAINTENANCE_OWNER = None
        _MAINTENANCE_TOKEN = None
        return True


def reset_maintenance_for_tests() -> None:
    """Reset only isolated test process state; never call in application flows."""
    global _ACTIVE_MCP_CALLS, _MAINTENANCE_OWNER, _MAINTENANCE_TOKEN
    with _MAINTENANCE_LOCK:
        _ACTIVE_MCP_CALLS = 0
        _MAINTENANCE_OWNER = None
        _MAINTENANCE_TOKEN = None

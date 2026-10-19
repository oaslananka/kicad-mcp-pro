"""Opt-in, server-observed MCP tool metadata trace for reviewed external agents.

This is *not* a complete ChatGPT session or publishable benchmark attempt.
Arguments, tool results, prompts, credentials and paths are never recorded.
"""

from __future__ import annotations

import asyncio
import os
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from mcp.server.context import CallNext, HandlerResult, ServerMiddleware, ServerRequestContext

from .reference_corpus import ReferenceAgentLogEvent

_TRACE_NAME = "ops-mcp-trace.jsonl"


class ReferenceOpsTrace:
    """Create a private, exclusive trace and append sanitized events in order."""

    def __init__(self, *, path: Path, attempt_id: str) -> None:
        if path.name != _TRACE_NAME or not path.is_absolute() or path.is_symlink():
            raise ValueError("Ops trace must be a new absolute ops-mcp-trace.jsonl file")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", attempt_id):
            raise ValueError("Ops trace attempt identity is invalid")
        parent = path.parent
        if (
            parent.is_symlink()
            or not parent.is_dir()
            or (os.name != "nt" and parent.stat().st_mode & 0o077)
        ):
            raise ValueError("Ops trace requires a private, real parent directory")
        self.attempt_id = attempt_id
        self._sequence = 0
        self._lock = asyncio.Lock()
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0)
        self._fd = os.open(path, flags, 0o600)
        self._closed = False

    async def emit(
        self, *, event_type: str, name: str, status: str, request_id: int | None = None
    ) -> int:
        async with self._lock:
            if self._closed:
                raise RuntimeError("Ops trace is closed")
            sequence = self._sequence + 1
            # Validation before the write means an invalid event cannot reach disk.
            event = ReferenceAgentLogEvent(
                attempt_id=self.attempt_id,
                sequence=sequence,
                timestamp=datetime.now(UTC),
                event_type=event_type,
                name=name,
                status=status,
                details={"provenance": "server_observed_mcp", "request_id": request_id},
            )
            line = (event.model_dump_json() + "\n").encode("utf-8")
            if os.write(self._fd, line) != len(line):
                raise OSError("short write to reference Ops tool trace")
            os.fsync(self._fd)
            self._sequence = sequence
            return sequence

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            os.close(self._fd)


class ReviewedOpsTraceMiddleware(ServerMiddleware[Any]):
    """Record transport-visible tool calls/results, never confidential payloads."""

    def __init__(self, trace: ReferenceOpsTrace) -> None:
        self.trace = trace

    async def __call__(
        self,
        context: ServerRequestContext[Any, Any],
        call_next: CallNext,
    ) -> HandlerResult:
        if context.method != "tools/call":
            return await call_next(context)
        params = context.params
        raw_name = params.get("name") if isinstance(params, Mapping) else None
        name = raw_name if isinstance(raw_name, str) else "unidentified_tool"
        request_id = await self.trace.emit(event_type="tool_call", name=name, status="started")
        try:
            result = await call_next(context)
        except BaseException:
            await self.trace.emit(
                event_type="tool_result",
                name=name,
                status="failed",
                request_id=request_id,
            )
            raise
        wire_is_error = (
            result.get("isError") is True
            if isinstance(result, dict)
            else getattr(result, "is_error", False) is True
        )
        await self.trace.emit(
            event_type="tool_result",
            name=name,
            status="failed" if wire_is_error else "completed",
            request_id=request_id,
        )
        return result


def configured_trace(*, checkout: Path) -> ReferenceOpsTrace | None:
    """Opt in only to an existing, isolated reference-run scratch directory."""
    raw_path = os.environ.get("KICAD_MCP_REFERENCE_TRACE_PATH")
    attempt_id = os.environ.get("KICAD_MCP_REFERENCE_ATTEMPT_ID")
    if raw_path is None and attempt_id is None:
        return None
    if not raw_path or not attempt_id:
        raise ValueError("Ops trace path and attempt ID must be configured together")
    path = Path(raw_path)
    root = (checkout / ".dev-tools/reference-agent-runs").resolve()
    # Never create the directory here: its owner must reserve an attempt first.
    if (
        not path.is_absolute()
        or not path.parent.is_relative_to(root)
        or not path.parent.resolve().is_relative_to(root)
    ):
        raise ValueError("Ops trace path must be inside the isolated reference runs area")
    if path.parent.name != attempt_id:
        raise ValueError("Ops trace path must use its reserved attempt directory")
    return ReferenceOpsTrace(path=path, attempt_id=attempt_id)

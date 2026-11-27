"""Reconcile Codex app-server 0.169.0 lifecycle notifications with a native MCP trace.

This is post-run evidence validation, not an execution sandbox, proof of model
identity, or a benchmark score. The caller must capture the complete lifecycle
of the selected turn; neither a client-supplied file nor matching metadata
authenticates its source. Only the reviewed initial schematic phase is supported.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Final, Literal

from . import reference_ops_trace_validation as trace_validation
from .reference_agent_runner import ReferenceAgentPhase, reviewed_mcp_tools
from .reference_corpus import ReferenceAgentLogEvent
from .reference_ops_reconciliation import _normalized_pairs

_CLIENT_FILENAME: Final = "codex-turn-events.jsonl"
_SERVER_FILENAME: Final = "ops-mcp-trace.jsonl"
_PROVENANCE = "client_supplied_codex"
_ITEM_STARTED = "item/started"
_ITEM_COMPLETED = "item/completed"
_TURN_STARTED = "turn/started"
_TURN_COMPLETED = "turn/completed"
_MCP_ITEM = "mcpToolCall"
_PASSIVE_ITEMS = frozenset(
    {"userMessage", "agentMessage", "reasoning", "plan", "contextCompaction"}
)
_TerminalStatus = Literal["completed", "failed", "interrupted"]
_ToolStatus = Literal["completed", "failed"]


class ReferenceCodexEvidenceError(ValueError):
    """Reject incomplete, inconsistent or unreviewed Codex turn evidence."""


@dataclass(frozen=True, slots=True)
class CodexTurnEvidence:
    """Matched, sanitized client/server tool metadata, explicitly non-scored."""

    status: str
    board_id: str
    attempt_id: str
    phase: str
    terminal_status: _TerminalStatus
    tool_calls: int
    failed_calls: int
    client_log_digest: str
    server_log_digest: str
    events: tuple[ReferenceAgentLogEvent, ...]
    counts_as_task_success: bool = False


def _object(value: object) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ReferenceCodexEvidenceError("Codex lifecycle record must be an object")
    return value


def _identity(value: object) -> str:
    if not isinstance(value, str) or not value or len(value) > 128:
        raise ReferenceCodexEvidenceError("invalid Codex lifecycle identity")
    return value


def _timestamp(value: object) -> datetime:
    if type(value) is not int or not 0 <= value <= 253402300799999:
        raise ReferenceCodexEvidenceError("invalid Codex lifecycle timestamp")
    return datetime(1970, 1, 1, tzinfo=UTC) + timedelta(milliseconds=value)


def _item_kind(item: Mapping[str, Any]) -> str:
    kind = item.get("type")
    if not isinstance(kind, str) or (kind != _MCP_ITEM and kind not in _PASSIVE_ITEMS):
        raise ReferenceCodexEvidenceError("unreviewed Codex execution item")
    return kind


def _tool_identity(item: Mapping[str, Any], allowed: frozenset[str]) -> tuple[str, str]:
    name = item.get("tool")
    if item.get("server") != "kicad" or not isinstance(name, str) or name not in allowed:
        raise ReferenceCodexEvidenceError("unreviewed Codex MCP server or tool")
    if item.get("pluginId") is not None:
        raise ReferenceCodexEvidenceError("plugin-scoped Codex MCP tool is not reviewed")
    return _identity(item.get("id")), name


def _tool_status(item: Mapping[str, Any]) -> _ToolStatus:
    status = item.get("status")
    if status == "completed" and item.get("error") is None:
        return "completed"
    if status == "failed":
        return "failed"
    raise ReferenceCodexEvidenceError("invalid Codex MCP completion status")


def _terminal_status(value: object) -> _TerminalStatus:
    if value == "completed":
        return "completed"
    if value == "failed":
        return "failed"
    if value == "interrupted":
        return "interrupted"
    raise ReferenceCodexEvidenceError("Codex turn has no terminal status")


@dataclass(slots=True)
class _TurnTracker:
    attempt_id: str
    thread_id: str
    turn_id: str
    allowed: frozenset[str]
    started: bool = False
    terminal: _TerminalStatus | None = None
    pending: tuple[str, str, int] | None = None
    completed: dict[str, tuple[str, _ToolStatus]] = field(default_factory=dict)
    events: list[ReferenceAgentLogEvent] = field(default_factory=list)

    def _emit(
        self,
        *,
        timestamp: datetime,
        name: str,
        status: Literal["started", "completed", "failed"],
        request_id: int | None,
    ) -> None:
        if self.events and timestamp < self.events[-1].timestamp:
            raise ReferenceCodexEvidenceError("Codex tool timestamps are out of order")
        self.events.append(
            ReferenceAgentLogEvent(
                attempt_id=self.attempt_id,
                sequence=len(self.events) + 1,
                timestamp=timestamp,
                event_type="tool_call" if status == "started" else "tool_result",
                name=name,
                status=status,
                details={"provenance": _PROVENANCE, "request_id": request_id},
            )
        )

    def _start_item(self, item: Mapping[str, Any], timestamp: datetime) -> None:
        identity, name = _tool_identity(item, self.allowed)
        if self.pending is not None or identity in self.completed:
            raise ReferenceCodexEvidenceError("overlapping or duplicate Codex MCP call")
        if item.get("status") != "inProgress":
            raise ReferenceCodexEvidenceError("invalid Codex MCP start status")
        self.pending = identity, name, len(self.events) + 1
        self._emit(timestamp=timestamp, name=name, status="started", request_id=None)

    def _complete_item(self, item: Mapping[str, Any], timestamp: datetime) -> None:
        identity, name = _tool_identity(item, self.allowed)
        if self.pending is None or self.pending[:2] != (identity, name):
            raise ReferenceCodexEvidenceError("unpaired or mismatched Codex MCP completion")
        status = _tool_status(item)
        self._emit(timestamp=timestamp, name=name, status=status, request_id=self.pending[2])
        self.completed[identity] = name, status
        self.pending = None

    def _check_terminal_items(self, turn: Mapping[str, Any]) -> None:
        items = turn.get("items")
        view = turn.get("itemsView", "full")
        if not isinstance(items, list) or view not in ("full", "summary", "notLoaded"):
            raise ReferenceCodexEvidenceError("invalid Codex terminal item view")
        if view == "notLoaded" and items:
            raise ReferenceCodexEvidenceError("unexpected unloaded Codex terminal items")
        observed: dict[str, tuple[str, _ToolStatus]] = {}
        for raw in items:
            item = _object(raw)
            if _item_kind(item) != _MCP_ITEM:
                continue
            identity, name = _tool_identity(item, self.allowed)
            if identity in observed:
                raise ReferenceCodexEvidenceError("duplicate Codex terminal MCP item")
            observed[identity] = name, _tool_status(item)
        if any(self.completed.get(key) != value for key, value in observed.items()):
            raise ReferenceCodexEvidenceError("Codex terminal history disagrees with lifecycle")
        if view == "full" and observed != self.completed:
            raise ReferenceCodexEvidenceError("Codex terminal history is incomplete")

    def _accept_turn(self, method: str, params: Mapping[str, Any]) -> None:
        turn = _object(params.get("turn"))
        if turn.get("id") != self.turn_id:
            raise ReferenceCodexEvidenceError("Codex turn identity mismatch")
        if method == _TURN_STARTED:
            if self.started or turn.get("status") != "inProgress" or turn.get("items") != []:
                raise ReferenceCodexEvidenceError("invalid Codex initial turn marker")
            self.started = True
            return
        if not self.started or self.pending is not None:
            raise ReferenceCodexEvidenceError("incomplete Codex turn lifecycle")
        self._check_terminal_items(turn)
        self.terminal = _terminal_status(turn.get("status"))

    def accept(self, row: Mapping[str, Any]) -> None:
        method = row.get("method")
        params = _object(row.get("params"))
        if params.get("threadId") != self.thread_id or self.terminal is not None:
            raise ReferenceCodexEvidenceError("foreign or post-terminal Codex notification")
        if method in (_TURN_STARTED, _TURN_COMPLETED):
            self._accept_turn(method, params)
            return
        if not self.started or params.get("turnId") != self.turn_id:
            raise ReferenceCodexEvidenceError("foreign or unstarted Codex item notification")
        if method not in (_ITEM_STARTED, _ITEM_COMPLETED):
            raise ReferenceCodexEvidenceError("unexpected Codex lifecycle notification")
        item = _object(params.get("item"))
        if _item_kind(item) != _MCP_ITEM:
            return
        if method == _ITEM_STARTED:
            self._start_item(item, _timestamp(params.get("startedAtMs")))
        else:
            self._complete_item(item, _timestamp(params.get("completedAtMs")))


def _parse_lifecycle(
    content: bytes, *, attempt_id: str, thread_id: str, turn_id: str
) -> tuple[_TerminalStatus, tuple[ReferenceAgentLogEvent, ...]]:
    phase = ReferenceAgentPhase.for_name("schematic")
    allowed = frozenset(name.removeprefix("mcp__kicad__") for name in reviewed_mcp_tools(phase))
    tracker = _TurnTracker(attempt_id, _identity(thread_id), _identity(turn_id), allowed)
    for line in content.splitlines():
        tracker.accept(_object(json.loads(line)))
    if tracker.terminal is None or not tracker.events or tracker.pending is not None:
        raise ReferenceCodexEvidenceError("incomplete Codex lifecycle evidence")
    return tracker.terminal, tuple(tracker.events)


def reconcile_codex_turn(
    server_path: Path,
    *,
    board_id: str,
    attempt_id: str,
    thread_id: str,
    turn_id: str,
) -> CodexTurnEvidence:
    """Compare a private reserved Codex lifecycle file against native MCP events.

    Only lifecycle notifications from the selected turn are expected. A trusted
    collector must preserve every item start/completion and turn marker; do not
    use this post-run check as a substitute for pre-execution tool isolation.
    """
    try:
        summary = trace_validation.validate_reference_ops_trace(
            server_path, attempt_id=attempt_id, phase_name="schematic", board_id=board_id
        )
        root = trace_validation._TRACE_ROOT
        client = trace_validation._load_trace(
            root=root, board_id=board_id, attempt_id=attempt_id, filename=_CLIENT_FILENAME
        )
        server = trace_validation._load_trace(
            root=root, board_id=board_id, attempt_id=attempt_id, filename=_SERVER_FILENAME
        )
        server_digest = "sha256:" + hashlib.sha256(server).hexdigest()
        if server_digest != summary.digest:
            raise ReferenceCodexEvidenceError("server trace changed during reconciliation")
        terminal, events = _parse_lifecycle(
            client, attempt_id=attempt_id, thread_id=thread_id, turn_id=turn_id
        )
        canonical = "".join(event.model_dump_json() + "\n" for event in events).encode("utf-8")
        server_pairs = _normalized_pairs(
            server, attempt_id=attempt_id, origin="server_observed_mcp"
        )
        client_pairs = _normalized_pairs(canonical, attempt_id=attempt_id, origin=_PROVENANCE)
        if client_pairs != server_pairs or len(client_pairs) != summary.tool_calls:
            raise ReferenceCodexEvidenceError("Codex and server tool events disagree")
        return CodexTurnEvidence(
            status="client_server_matched_unattested",
            board_id=board_id,
            attempt_id=attempt_id,
            phase="schematic",
            terminal_status=terminal,
            tool_calls=summary.tool_calls,
            failed_calls=summary.failed_calls,
            client_log_digest="sha256:" + hashlib.sha256(client).hexdigest(),
            server_log_digest=server_digest,
            events=events,
        )
    except (OSError, ValueError, TypeError, OverflowError) as exc:
        if isinstance(exc, ReferenceCodexEvidenceError):
            raise
        raise ReferenceCodexEvidenceError("invalid or unauthorized Codex turn evidence") from exc

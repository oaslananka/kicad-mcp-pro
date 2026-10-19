"""Validate a server-observed Ops tool trace before benchmark reconciliation.

A valid trace only proves a complete ordered server-side tool-event ledger;
it does not prove client intent or independent task success.
"""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from pydantic import ValidationError

from .reference_agent_runner import ReferenceAgentPhase, reviewed_mcp_tools
from .reference_corpus import REFERENCE_IDENTIFIER_PATTERN, ReferenceAgentLogEvent

_MAX_TRACE_BYTES = 2_000_000
_MAX_EVENTS = 10_000
_TRACE_ROOT = Path(__file__).resolve().parents[3] / ".dev-tools/reference-agent-runs"


class ReferenceOpsTraceValidationError(ValueError):
    """Reject untrusted, incomplete or unpaired server-side tool evidence."""


@dataclass(frozen=True, slots=True)
class ReferenceOpsTraceSummary:
    attempt_id: str
    phase: str
    tool_calls: int
    failed_calls: int
    digest: str
    counts_as_task_success: bool = False


def _approved_trace_path(path: Path, attempt_id: str) -> Path:
    """Resolve only the reserved trace location, never an arbitrary CLI path."""
    if not re.fullmatch(REFERENCE_IDENTIFIER_PATTERN, attempt_id) or attempt_id in {".", ".."}:
        raise ReferenceOpsTraceValidationError("invalid reference attempt identifier")
    expected = _TRACE_ROOT / attempt_id / "ops-mcp-trace.jsonl"
    if (
        not path.is_absolute()
        or path != expected
        or path.is_symlink()
        or path.parent.is_symlink()
        or _TRACE_ROOT.is_symlink()
    ):
        raise ReferenceOpsTraceValidationError("trace must be in its reserved private directory")
    if expected.resolve().parent != (_TRACE_ROOT / attempt_id).resolve():
        raise ReferenceOpsTraceValidationError("trace directory escaped its reservation")
    return expected


def _load_trace(path: Path) -> bytes:
    stat = path.stat()
    if not path.is_file() or not 0 < stat.st_size <= _MAX_TRACE_BYTES:
        raise ReferenceOpsTraceValidationError("trace is absent, empty or oversized")
    if os.name != "nt" and stat.st_mode & 0o077:
        raise ReferenceOpsTraceValidationError("trace must remain private")
    content = path.read_bytes()
    if len(content) != stat.st_size or not content.endswith(b"\n"):
        raise ReferenceOpsTraceValidationError("trace is incomplete or changed during read")
    if not 0 < len(content.splitlines()) <= _MAX_EVENTS:
        raise ReferenceOpsTraceValidationError("trace event count is invalid")
    if path.stat().st_size != len(content):
        raise ReferenceOpsTraceValidationError("trace changed during validation")
    return content


def _check_event(
    event: ReferenceAgentLogEvent,
    *,
    number: int,
    attempt_id: str,
    allowed: set[str],
    previous_timestamp: datetime | None,
) -> None:
    if event.attempt_id != attempt_id or event.sequence != number:
        raise ReferenceOpsTraceValidationError("event identity or sequence mismatch")
    if event.name not in allowed:
        raise ReferenceOpsTraceValidationError("unreviewed tool in server trace")
    if previous_timestamp is not None and event.timestamp < previous_timestamp:
        raise ReferenceOpsTraceValidationError("event timestamps are out of order")
    if set(event.details) != {"provenance", "request_id"}:
        raise ReferenceOpsTraceValidationError("unexpected event detail fields")
    if event.details["provenance"] != "server_observed_mcp":
        raise ReferenceOpsTraceValidationError("event provenance is invalid")


def _track_tool_event(
    event: ReferenceAgentLogEvent, number: int, outstanding: dict[int, str]
) -> bool | None:
    request_id = event.details["request_id"]
    if event.event_type == "tool_call":
        if event.status != "started" or request_id is not None:
            raise ReferenceOpsTraceValidationError("invalid tool call marker")
        outstanding[number] = event.name
        return None
    if event.event_type == "tool_result":
        if (
            event.status not in {"completed", "failed"}
            or type(request_id) is not int
            or outstanding.pop(request_id, None) != event.name
        ):
            raise ReferenceOpsTraceValidationError("unpaired or inconsistent tool result")
        return event.status == "failed"
    raise ReferenceOpsTraceValidationError("non-tool event in server trace")


def _verify_events(
    content: bytes, *, attempt_id: str, phase: ReferenceAgentPhase
) -> tuple[int, int]:
    allowed = {name.removeprefix("mcp__kicad__") for name in reviewed_mcp_tools(phase)}
    outstanding: dict[int, str] = {}
    previous_timestamp: datetime | None = None
    failures = calls = 0
    for number, raw in enumerate(content.splitlines(), start=1):
        event = ReferenceAgentLogEvent.model_validate_json(raw)
        _check_event(
            event,
            number=number,
            attempt_id=attempt_id,
            allowed=allowed,
            previous_timestamp=previous_timestamp,
        )
        previous_timestamp = event.timestamp
        outcome = _track_tool_event(event, number, outstanding)
        if outcome is None:
            calls += 1
        elif outcome:
            failures += 1
    if not calls or outstanding:
        raise ReferenceOpsTraceValidationError("no complete server tool calls")
    return calls, failures


def validate_reference_ops_trace(
    path: Path, *, attempt_id: str, phase_name: str
) -> ReferenceOpsTraceSummary:
    """Fail closed on unauthorized paths and malformed or unpaired tool events."""
    phase = ReferenceAgentPhase.for_name(phase_name)
    if phase.name == "manufacturing":
        raise ReferenceOpsTraceValidationError("manufacturing trace is not approved")
    try:
        trace = _approved_trace_path(path, attempt_id)
        content = _load_trace(trace)
        calls, failures = _verify_events(content, attempt_id=attempt_id, phase=phase)
    except (OSError, UnicodeError, ValidationError) as exc:
        raise ReferenceOpsTraceValidationError("invalid server trace content or file") from exc
    return ReferenceOpsTraceSummary(
        attempt_id=attempt_id,
        phase=phase.name,
        tool_calls=calls,
        failed_calls=failures,
        digest="sha256:" + hashlib.sha256(content).hexdigest(),
    )

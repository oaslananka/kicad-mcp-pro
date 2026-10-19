"""Validate a server-observed Ops tool trace before any benchmark reconciliation.

A valid trace is only a complete, ordered *server-side* tool-event ledger.
It cannot establish the model's full client transcript or task success.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from .reference_agent_runner import ReferenceAgentPhase, reviewed_mcp_tools
from .reference_corpus import ReferenceAgentLogEvent

_MAX_TRACE_BYTES = 2_000_000
_MAX_EVENTS = 10_000


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


def validate_reference_ops_trace(
    path: Path, *, attempt_id: str, phase_name: str
) -> ReferenceOpsTraceSummary:
    """Fail closed on malformed, unreviewed, missing or reordered tool events."""
    phase = ReferenceAgentPhase.for_name(phase_name)
    if phase.name == "manufacturing":
        raise ReferenceOpsTraceValidationError("manufacturing trace is not approved")
    if path.name != "ops-mcp-trace.jsonl" or not path.is_absolute() or path.is_symlink():
        raise ReferenceOpsTraceValidationError("trace must be an absolute regular Ops file")
    try:
        stat = path.stat()
        if not path.is_file() or not 0 < stat.st_size <= _MAX_TRACE_BYTES:
            raise ReferenceOpsTraceValidationError("trace is absent, empty or oversized")
        if os.name != "nt" and stat.st_mode & 0o077:
            raise ReferenceOpsTraceValidationError("trace must remain private")
        content = path.read_bytes()
        if len(content) != stat.st_size or not content.endswith(b"\n"):
            raise ReferenceOpsTraceValidationError("trace is incomplete or changed during read")
        lines = content.splitlines()
        if not 0 < len(lines) <= _MAX_EVENTS:
            raise ReferenceOpsTraceValidationError("trace event count is invalid")
        allowed = {name.removeprefix("mcp__kicad__") for name in reviewed_mcp_tools(phase)}
        outstanding: dict[int, str] = {}
        previous_timestamp = None
        failures = calls = 0
        for number, raw in enumerate(lines, start=1):
            event = ReferenceAgentLogEvent.model_validate_json(raw)
            if event.attempt_id != attempt_id or event.sequence != number:
                raise ReferenceOpsTraceValidationError("event identity or sequence mismatch")
            if event.name not in allowed:
                raise ReferenceOpsTraceValidationError("unreviewed tool in server trace")
            if previous_timestamp is not None and event.timestamp < previous_timestamp:
                raise ReferenceOpsTraceValidationError("event timestamps are out of order")
            previous_timestamp = event.timestamp
            if set(event.details) != {"provenance", "request_id"}:
                raise ReferenceOpsTraceValidationError("unexpected event detail fields")
            if event.details["provenance"] != "server_observed_mcp":
                raise ReferenceOpsTraceValidationError("event provenance is invalid")
            request_id = event.details["request_id"]
            if event.event_type == "tool_call":
                if event.status != "started" or request_id is not None:
                    raise ReferenceOpsTraceValidationError("invalid tool call marker")
                outstanding[number] = event.name
                calls += 1
            elif event.event_type == "tool_result":
                if (
                    event.status not in {"completed", "failed"}
                    or type(request_id) is not int
                    or outstanding.pop(request_id, None) != event.name
                ):
                    raise ReferenceOpsTraceValidationError("unpaired or inconsistent tool result")
                failures += event.status == "failed"
            else:
                raise ReferenceOpsTraceValidationError("non-tool event in server trace")
        if not calls or outstanding:
            raise ReferenceOpsTraceValidationError("no complete server tool calls")
        if path.stat().st_size != len(content):
            raise ReferenceOpsTraceValidationError("trace changed during validation")
    except (OSError, UnicodeError, ValidationError) as exc:
        raise ReferenceOpsTraceValidationError("invalid server trace content or file") from exc
    return ReferenceOpsTraceSummary(
        attempt_id=attempt_id,
        phase=phase.name,
        tool_calls=calls,
        failed_calls=failures,
        digest="sha256:" + hashlib.sha256(content).hexdigest(),
    )

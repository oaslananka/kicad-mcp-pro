"""Compare distinct server and client tool metadata, without claiming client identity.

This intentionally narrow reconciler accepts only sequential calls on one
isolated attempt. Independent authentication and benchmark scoring are
different requirements: a matching client-supplied file remains UNATTESTED.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from pydantic import ValidationError

from .reference_corpus import ReferenceAgentLogEvent
from .reference_ops_trace_validation import (
    ReferenceOpsTraceValidationError,
    _load_trace,
    validate_reference_ops_trace,
)

_TRACE_ROOT = Path(__file__).resolve().parents[3] / ".dev-tools/reference-agent-runs"
_CLIENT_NAME = "ops-client-observed.jsonl"


class ReferenceOpsReconciliationError(ValueError):
    """Reject incomplete, unsafe or nonmatching client/server metadata."""


@dataclass(frozen=True, slots=True)
class ReferenceOpsReconciliationSummary:
    status: str
    attempt_id: str
    phase: str
    tool_calls: int
    failed_calls: int
    client_log_digest: str
    server_log_digest: str
    counts_as_task_success: bool = False


def _client_bytes(client_path: Path, server_path: Path, attempt_id: str) -> bytes:
    expected = _TRACE_ROOT / attempt_id / _CLIENT_NAME
    if (
        client_path != expected
        or not client_path.is_absolute()
        or client_path.is_symlink()
        or client_path.parent.is_symlink()
        or _TRACE_ROOT.is_symlink()
        or server_path != expected.with_name("ops-mcp-trace.jsonl")
        or expected.resolve().parent != (_TRACE_ROOT / attempt_id).resolve()
    ):
        raise ReferenceOpsReconciliationError("client file must be in the reserved trace directory")
    if os.name != "nt" and client_path.parent.stat().st_mode & 0o077:
        raise ReferenceOpsReconciliationError("client evidence directory must be private")
    return _load_trace(
        root=_TRACE_ROOT, attempt_id=attempt_id, filename="ops-client-observed.jsonl"
    )


def _validate_event_metadata(
    event: ReferenceAgentLogEvent,
    *,
    attempt_id: str,
    sequence: int,
    previous_timestamp: datetime | None,
    origin: str,
) -> None:
    """Preserve the reconciliation checks and their existing error ordering."""
    if event.attempt_id != attempt_id or event.sequence != sequence:
        raise ReferenceOpsReconciliationError("event identity or sequence mismatch")
    if previous_timestamp is not None and event.timestamp < previous_timestamp:
        raise ReferenceOpsReconciliationError("event timestamps are out of order")
    if set(event.details) != {"provenance", "request_id"}:
        raise ReferenceOpsReconciliationError("unexpected event detail fields")
    if event.details["provenance"] != origin:
        raise ReferenceOpsReconciliationError("event provenance mismatch")


def _validate_tool_call(
    event: ReferenceAgentLogEvent, *, pending: tuple[str, int] | None, sequence: int
) -> tuple[str, int]:
    if pending is not None or event.status != "started" or event.details["request_id"] is not None:
        raise ReferenceOpsReconciliationError("overlapping or malformed client/tool call")
    return event.name, sequence


def _validated_tool_result(
    event: ReferenceAgentLogEvent, *, pending: tuple[str, int] | None
) -> tuple[str, str]:
    if (
        pending is None
        or event.name != pending[0]
        or event.status not in {"completed", "failed"}
        or type(event.details["request_id"]) is not int
        or event.details["request_id"] != pending[1]
    ):
        raise ReferenceOpsReconciliationError("unpaired or mismatched result")
    return event.name, event.status


def _normalized_pairs(content: bytes, *, attempt_id: str, origin: str) -> list[tuple[str, str]]:
    """Extract complete sequential calls; concurrent/interleaved cases are not attested."""
    pending: tuple[str, int] | None = None
    result: list[tuple[str, str]] = []
    previous_timestamp: datetime | None = None
    for seq, raw in enumerate(content.splitlines(), start=1):
        event = ReferenceAgentLogEvent.model_validate_json(raw)
        _validate_event_metadata(
            event,
            attempt_id=attempt_id,
            sequence=seq,
            previous_timestamp=previous_timestamp,
            origin=origin,
        )
        previous_timestamp = event.timestamp
        if event.event_type == "tool_call":
            pending = _validate_tool_call(event, pending=pending, sequence=seq)
        elif event.event_type == "tool_result":
            result.append(_validated_tool_result(event, pending=pending))
            pending = None
        else:
            raise ReferenceOpsReconciliationError("unexpected non-tool event")
    if pending is not None or not result:
        raise ReferenceOpsReconciliationError("incomplete tool sequence")
    return result


def reconcile_ops_events(
    server_path: Path, client_path: Path, *, attempt_id: str, phase_name: str
) -> ReferenceOpsReconciliationSummary:
    """Verify metadata agreement, never client authenticity or task success."""
    try:
        server_summary = validate_reference_ops_trace(
            server_path, attempt_id=attempt_id, phase_name=phase_name
        )
        client_bytes = _client_bytes(client_path, server_path, attempt_id)
        server_bytes = _load_trace(
            root=_TRACE_ROOT, attempt_id=attempt_id, filename="ops-mcp-trace.jsonl"
        )
        if "sha256:" + hashlib.sha256(server_bytes).hexdigest() != server_summary.digest:
            raise ReferenceOpsReconciliationError("server trace changed during reconciliation")
        server_pairs = _normalized_pairs(
            server_bytes, attempt_id=attempt_id, origin="server_observed_mcp"
        )
        client_pairs = _normalized_pairs(
            client_bytes, attempt_id=attempt_id, origin="client_supplied_ops"
        )
        if (
            server_pairs != client_pairs
            or len(server_pairs) != server_summary.tool_calls
            or sum(status == "failed" for _, status in server_pairs) != server_summary.failed_calls
        ):
            raise ReferenceOpsReconciliationError("client and server tool events disagree")
        return ReferenceOpsReconciliationSummary(
            status="client_server_matched_unattested",
            attempt_id=attempt_id,
            phase=phase_name,
            tool_calls=len(server_pairs),
            failed_calls=sum(status == "failed" for _, status in server_pairs),
            client_log_digest="sha256:" + hashlib.sha256(client_bytes).hexdigest(),
            server_log_digest=server_summary.digest,
        )
    except (OSError, UnicodeError, ValidationError, ReferenceOpsTraceValidationError) as exc:
        raise ReferenceOpsReconciliationError(
            "invalid or unauthorized client/server evidence"
        ) from exc

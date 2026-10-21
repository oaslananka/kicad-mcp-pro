"""Validate a server-observed Ops tool trace before benchmark reconciliation.

A valid trace only proves a complete ordered server-side tool-event ledger;
it does not prove client intent or independent task success.
"""

from __future__ import annotations

import hashlib
import os
import re
import stat as stat_module
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Final, Literal

from pydantic import ValidationError

from .reference_agent_runner import ReferenceAgentPhase, reviewed_mcp_tools
from .reference_corpus import REFERENCE_IDENTIFIER_PATTERN, ReferenceAgentLogEvent

_MAX_TRACE_BYTES = 2_000_000
_MAX_EVENTS = 10_000
_TRACE_ROOT = Path(__file__).resolve().parents[3] / ".dev-tools/reference-agent-runs"
_TRACE_FILENAME: Final = "ops-mcp-trace.jsonl"
_ERR_RESERVED_DIRECTORY: Final = "trace must be in its reserved private directory"


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
    expected = _TRACE_ROOT / attempt_id / _TRACE_FILENAME
    if (
        not path.is_absolute()
        or path != expected
        or path.is_symlink()
        or path.parent.is_symlink()
        or _TRACE_ROOT.is_symlink()
    ):
        raise ReferenceOpsTraceValidationError(_ERR_RESERVED_DIRECTORY)
    if expected.resolve().parent != (_TRACE_ROOT / attempt_id).resolve():
        raise ReferenceOpsTraceValidationError("trace directory escaped its reservation")
    return expected


def _open_reserved_trace(*, root: Path, attempt_id: str, filename: str) -> int:
    """Open the reserved trace without following a replaced directory or file."""
    # Windows CRT defaults os.open to text mode; CRLF translation changes
    # the byte count read and falsely trips the exact-size trace check.
    flags = (
        os.O_RDONLY
        | getattr(os, "O_BINARY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )
    if os.name == "nt":
        directory = root / attempt_id
        expected = directory / filename
        if directory.is_symlink() or expected.is_symlink():
            raise ReferenceOpsTraceValidationError(_ERR_RESERVED_DIRECTORY)
        return os.open(expected, flags)

    directory_flags = flags | getattr(os, "O_DIRECTORY", 0)
    root_fd = os.open(root, directory_flags)
    try:
        directory_fd = os.open(attempt_id, directory_flags, dir_fd=root_fd)
        try:
            if os.fstat(directory_fd).st_mode & 0o077:
                raise ReferenceOpsTraceValidationError("trace directory must be private")
            return os.open(filename, flags, dir_fd=directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        os.close(root_fd)


def _read_open_trace(fd: int, *, require_jsonl: bool = True) -> bytes:
    """Read a bounded regular file and detect changes on the same descriptor."""
    before = os.fstat(fd)
    if not stat_module.S_ISREG(before.st_mode) or not 0 < before.st_size <= _MAX_TRACE_BYTES:
        raise ReferenceOpsTraceValidationError("trace is absent, empty or oversized")
    if os.name != "nt" and before.st_mode & 0o077:
        raise ReferenceOpsTraceValidationError("trace must remain private")
    content = bytearray()
    while len(content) <= _MAX_TRACE_BYTES:
        chunk = os.read(fd, min(65536, _MAX_TRACE_BYTES + 1 - len(content)))
        if not chunk:
            break
        content.extend(chunk)
    after = os.fstat(fd)
    if (
        len(content) != before.st_size
        or before.st_size != after.st_size
        or before.st_mtime_ns != after.st_mtime_ns
        or before.st_ino != after.st_ino
        or (require_jsonl and not content.endswith(b"\n"))
    ):
        raise ReferenceOpsTraceValidationError("trace is incomplete or changed during read")
    result = bytes(content)
    if require_jsonl and not 0 < len(result.splitlines()) <= _MAX_EVENTS:
        raise ReferenceOpsTraceValidationError("trace event count is invalid")
    return result


def _load_trace(
    *,
    root: Path,
    attempt_id: str,
    filename: Literal[
        "ops-mcp-trace.jsonl",
        "ops-client-observed.jsonl",
        "ops-gateway-audit.json",
        "signed-gateway-witness.json",
    ],
) -> bytes:
    """Read fixed evidence only, never opening the untrusted CLI pathname."""
    if (
        not re.fullmatch(REFERENCE_IDENTIFIER_PATTERN, attempt_id)
        or attempt_id in {".", ".."}
        or not root.is_absolute()
        or root.is_symlink()
        or root.parent.is_symlink()
        or filename
        not in {
            _TRACE_FILENAME,
            "ops-client-observed.jsonl",
            "ops-gateway-audit.json",
            "signed-gateway-witness.json",
        }
    ):
        raise ReferenceOpsTraceValidationError(_ERR_RESERVED_DIRECTORY)
    fd = _open_reserved_trace(root=root, attempt_id=attempt_id, filename=filename)
    try:
        return _read_open_trace(fd, require_jsonl=filename != "signed-gateway-witness.json")
    finally:
        os.close(fd)


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
        _approved_trace_path(path, attempt_id)
        content = _load_trace(root=_TRACE_ROOT, attempt_id=attempt_id, filename=_TRACE_FILENAME)
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

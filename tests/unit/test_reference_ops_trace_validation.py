"""Deterministic adversarial validation of genuine server-observed tool traces."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import pytest

from kicad_mcp.evals.reference_ops_trace import ReferenceOpsTrace
from kicad_mcp.evals.reference_ops_trace_validation import (
    ReferenceOpsTraceValidationError,
    validate_reference_ops_trace,
)


def _good_trace(tmp_path: Path) -> Path:
    parent = tmp_path / "private"
    parent.mkdir(mode=0o700)
    parent.chmod(0o700)
    path = parent / "ops-mcp-trace.jsonl"

    async def write_events() -> None:
        trace = ReferenceOpsTrace(path=path, attempt_id="attempt-004")
        try:
            call = await trace.emit(
                event_type="tool_call", name="kicad_get_version", status="started"
            )
            await trace.emit(
                event_type="tool_result",
                name="kicad_get_version",
                status="completed",
                request_id=call,
            )
            call = await trace.emit(
                event_type="tool_call", name="kicad_get_server_info", status="started"
            )
            await trace.emit(
                event_type="tool_result",
                name="kicad_get_server_info",
                status="failed",
                request_id=call,
            )
        finally:
            trace.close()

    asyncio.run(write_events())
    return path


def test_valid_real_emitted_trace_is_not_benchmark_success(tmp_path: Path) -> None:
    path = _good_trace(tmp_path)
    summary = validate_reference_ops_trace(path, attempt_id="attempt-004", phase_name="schematic")
    assert summary.tool_calls == 2
    assert summary.failed_calls == 1
    assert summary.digest.startswith("sha256:")
    assert summary.counts_as_task_success is False


@pytest.mark.parametrize(
    "change",
    [
        "missing-result",
        "duplicate-result",
        "out-of-sequence",
        "wrong-identity",
        "mismatched-name",
        "unreviewed-name",
        "unexpected-payload",
        "incorrect-request-id",
        "invalid-provenance",
        "empty-trace",
    ],
)
def test_fail_closed_on_tampered_events(tmp_path: Path, change: str) -> None:
    path = _good_trace(tmp_path)
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    if change == "missing-result":
        rows.pop()
    elif change == "duplicate-result":
        rows.append(dict(rows[-1], sequence=5))
    elif change == "out-of-sequence":
        rows[2]["sequence"] = 50
    elif change == "wrong-identity":
        rows[1]["attempt_id"] = "attempt-999"
    elif change == "mismatched-name":
        rows[1]["name"] = "kicad_get_server_info"
    elif change == "unreviewed-name":
        rows[0]["name"] = "drc_rule_delete"
    elif change == "unexpected-payload":
        rows[1]["details"]["arguments"] = "not-a-safe-field"
    elif change == "incorrect-request-id":
        rows[3]["details"]["request_id"] = 101
    elif change == "invalid-provenance":
        rows[0]["details"]["provenance"] = "user_supplied"
    else:
        rows = []
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    with pytest.raises(ReferenceOpsTraceValidationError):
        validate_reference_ops_trace(path, attempt_id="attempt-004", phase_name="schematic")


def test_public_or_symlinked_trace_is_rejected(tmp_path: Path) -> None:
    path = _good_trace(tmp_path)
    if os.name != "nt":
        path.chmod(0o644)
        with pytest.raises(ReferenceOpsTraceValidationError, match="private"):
            validate_reference_ops_trace(path, attempt_id="attempt-004", phase_name="schematic")
        path.chmod(0o600)
    link = tmp_path / "ops-mcp-trace.jsonl"
    try:
        link.symlink_to(path)
    except OSError:
        pytest.skip("symlink creation unavailable on this platform")
    with pytest.raises(ReferenceOpsTraceValidationError):
        validate_reference_ops_trace(link, attempt_id="attempt-004", phase_name="schematic")


def test_manufacturing_trace_cannot_be_accepted(tmp_path: Path) -> None:
    path = _good_trace(tmp_path)
    with pytest.raises(ReferenceOpsTraceValidationError, match="manufacturing"):
        validate_reference_ops_trace(path, attempt_id="attempt-004", phase_name="manufacturing")


@pytest.mark.parametrize(
    "mutation",
    [
        "truncated-last-line",
        "too-many-events",
        "timestamp-regression",
        "invalid-call-status",
        "non-tool-event",
        "malformed-json",
    ],
)
def test_other_incomplete_or_untrusted_trace_conditions_fail_closed(
    tmp_path: Path, mutation: str
) -> None:
    path = _good_trace(tmp_path)
    if mutation == "truncated-last-line":
        path.write_bytes(path.read_bytes().rstrip(b"\n"))
    elif mutation == "too-many-events":
        path.write_bytes(b"{}\n" * 10001)
    elif mutation == "malformed-json":
        path.write_bytes(b"{not-json}\n")
    else:
        rows = [json.loads(row) for row in path.read_text().splitlines()]
        if mutation == "timestamp-regression":
            rows[2]["timestamp"] = "2000-01-01T00:00:00+00:00"
        elif mutation == "invalid-call-status":
            rows[0]["status"] = "completed"
        elif mutation == "non-tool-event":
            rows[0]["event_type"] = "agent"
        path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    with pytest.raises(ReferenceOpsTraceValidationError):
        validate_reference_ops_trace(path, attempt_id="attempt-004", phase_name="schematic")

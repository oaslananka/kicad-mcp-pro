"""Reconcile a separately exported Ops Gateway audit witness with MCP trace.

A gateway SQLite audit snapshot is a *separate observation*, not authenticated
client/model provenance. Matching metadata must never award task success.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .reference_corpus import ReferenceAgentLogEvent
from .reference_ops_reconciliation import _normalized_pairs
from .reference_ops_trace_validation import (
    _load_trace,
    validate_reference_ops_trace,
)

_TRACE_ROOT = Path(__file__).resolve().parents[3] / ".dev-tools/reference-agent-runs"
_MAX_CLOCK_SKEW_SECONDS = 30
_MAX_DURATION_SKEW_MS = 15000
_VALID_SERVER_NAME = re.compile(r"kicad-[a-z0-9-]{1,72}\Z")


class ReferenceOpsGatewayAuditError(ValueError):
    """Gateway export or independent tool observations cannot be reconciled."""


@dataclass(frozen=True, slots=True)
class GatewayAuditReconciliationSummary:
    status: str
    attempt_id: str
    phase: str
    tool_calls: int
    first_audit_id: int
    last_audit_id: int
    gateway_log_digest: str
    server_log_digest: str
    counts_as_task_success: bool = False


_EXPECTED_WITNESS_FIELDS = {
    "schema_version",
    "source",
    "observed_on",
    "device",
    "tool_prefix",
    "capture_utc",
    "client_count",
    "rows",
}
_EXPECTED_ROW_FIELDS = {"id", "at", "tool", "device", "status", "duration_ms"}
_ALLOWED_STATUSES = {"ok", "error", "refused", "timeout", "offline"}


def _validate_witness_header(payload: object, prefix: str) -> None:
    if not isinstance(payload, dict) or set(payload) != _EXPECTED_WITNESS_FIELDS:
        raise ReferenceOpsGatewayAuditError("Gateway witness schema or source mismatch")
    if (
        payload["schema_version"] != "ops-gateway-audit-witness.v1"
        or payload["source"] != "ops-gateway-sqlite-readonly"
        or payload["observed_on"] != "vps"
        or payload["device"] != "msi"
        or payload["tool_prefix"] != prefix
        or type(payload["client_count"]) is not int
        or payload["client_count"] != 1
        or not isinstance(payload["capture_utc"], str)
    ):
        raise ReferenceOpsGatewayAuditError("Gateway witness schema or source mismatch")
    try:
        capture = datetime.fromisoformat(payload["capture_utc"].replace("Z", "+00:00"))
        if capture.tzinfo is None:
            raise ValueError("missing timezone")
    except ValueError as exc:
        raise ReferenceOpsGatewayAuditError("invalid Gateway capture timestamp") from exc


def _is_valid_witness_row(row: object, prefix: str, previous_id: int, previous_time: int) -> bool:
    if not isinstance(row, dict) or set(row) != _EXPECTED_ROW_FIELDS:
        return False
    if (
        type(row["id"]) is not int
        or type(row["at"]) is not int
        or type(row["duration_ms"]) is not int
    ):
        return False
    if row["id"] <= previous_id or row["at"] < previous_time or row["duration_ms"] < 0:
        return False
    if (
        row["device"] != "msi"
        or not isinstance(row["status"], str)
        or not isinstance(row["tool"], str)
    ):
        return False
    return row["tool"].startswith(prefix) and row["status"] in _ALLOWED_STATUSES


def _witness_rows(content: bytes, server_name: str) -> list[dict[str, Any]]:
    try:
        payload = json.loads(content)
    except ValueError as exc:
        raise ReferenceOpsGatewayAuditError("invalid Gateway witness JSON") from exc
    prefix = f"pc.msi.mcp.{server_name}."
    _validate_witness_header(payload, prefix)
    rows = payload["rows"]
    if not isinstance(rows, list) or not rows:
        raise ReferenceOpsGatewayAuditError("Gateway witness has no tool calls")
    previous_id = 0
    previous_time = 0
    for row in rows:
        if not _is_valid_witness_row(row, prefix, previous_id, previous_time):
            raise ReferenceOpsGatewayAuditError("Gateway audit rows are invalid or unordered")
        previous_id = row["id"]
        previous_time = row["at"]
    return rows


def _match_gateway_server_events(
    *,
    rows: list[dict[str, Any]],
    calls: list[ReferenceAgentLogEvent],
    results: list[ReferenceAgentLogEvent],
    pairs: list[tuple[str, str]],
    server_name: str,
) -> None:
    """Compare gateway timing/order against independent server observations."""
    if len(rows) != len(pairs) or len(results) != len(pairs) or len(calls) != len(pairs):
        raise ReferenceOpsGatewayAuditError("Gateway/server call counts differ")
    prefix = f"pc.msi.mcp.{server_name}."
    for audit, call, result, (name, state) in zip(rows, calls, results, pairs, strict=True):
        if audit["tool"].removeprefix(prefix) != name:
            raise ReferenceOpsGatewayAuditError("Gateway/server tool order differs")
        if (audit["status"] == "ok") != (state == "completed"):
            raise ReferenceOpsGatewayAuditError("Gateway failure disagrees with server")
        duration = (result.timestamp - call.timestamp).total_seconds() * 1000
        if duration < 0 or abs(audit["duration_ms"] - duration) > _MAX_DURATION_SKEW_MS:
            raise ReferenceOpsGatewayAuditError("Gateway/server call durations differ")
        if abs(audit["at"] - result.timestamp.timestamp()) > _MAX_CLOCK_SKEW_SECONDS:
            raise ReferenceOpsGatewayAuditError("Gateway/server call times differ")


def reconcile_gateway_audit(
    server_path: Path,
    gateway_path: Path,
    *,
    attempt_id: str,
    phase_name: str,
    server_name: str,
) -> GatewayAuditReconciliationSummary:
    """Check bounded, distinct observations; NEVER authenticate the exporter."""
    if not _VALID_SERVER_NAME.fullmatch(server_name):
        raise ReferenceOpsGatewayAuditError("invalid reviewed Ops MCP server name")
    expected_dir = _TRACE_ROOT / attempt_id
    if gateway_path != expected_dir / "ops-gateway-audit.json":
        raise ReferenceOpsGatewayAuditError("Gateway witness path is not reserved")
    if server_path != expected_dir / "ops-mcp-trace.jsonl":
        raise ReferenceOpsGatewayAuditError("server trace path is not reserved")
    try:
        summary = validate_reference_ops_trace(
            server_path, attempt_id=attempt_id, phase_name=phase_name
        )
        server_bytes = _load_trace(
            root=_TRACE_ROOT, attempt_id=attempt_id, filename="ops-mcp-trace.jsonl"
        )
        gateway_bytes = _load_trace(
            root=_TRACE_ROOT, attempt_id=attempt_id, filename="ops-gateway-audit.json"
        )
        if hashlib.sha256(server_bytes).hexdigest() != summary.digest.removeprefix("sha256:"):
            raise ReferenceOpsGatewayAuditError("server trace changed during validation")
        pairs = _normalized_pairs(server_bytes, attempt_id=attempt_id, origin="server_observed_mcp")
        events = [ReferenceAgentLogEvent.model_validate_json(e) for e in server_bytes.splitlines()]
        results = [event for event in events if event.event_type == "tool_result"]
        calls = [event for event in events if event.event_type == "tool_call"]
        rows = _witness_rows(gateway_bytes, server_name)
        if len(rows) != summary.tool_calls:
            raise ReferenceOpsGatewayAuditError("Gateway/server call counts differ")
        _match_gateway_server_events(
            rows=rows, calls=calls, results=results, pairs=pairs, server_name=server_name
        )
        return GatewayAuditReconciliationSummary(
            status="gateway_server_matched_unattested",
            attempt_id=attempt_id,
            phase=phase_name,
            tool_calls=len(rows),
            first_audit_id=rows[0]["id"],
            last_audit_id=rows[-1]["id"],
            gateway_log_digest="sha256:" + hashlib.sha256(gateway_bytes).hexdigest(),
            server_log_digest=summary.digest,
        )
    except (OSError, ValueError) as exc:
        if isinstance(exc, ReferenceOpsGatewayAuditError):
            raise
        raise ReferenceOpsGatewayAuditError(
            "invalid or unauthorized Gateway/server evidence"
        ) from exc

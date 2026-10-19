"""Untrusted client/server event reconciliation must never imply benchmark success."""

from __future__ import annotations

import asyncio
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from kicad_mcp.evals import reference_ops_reconciliation, reference_ops_trace_validation
from kicad_mcp.evals.reference_corpus import ReferenceAgentLogEvent
from kicad_mcp.evals.reference_ops_reconciliation import (
    ReferenceOpsReconciliationError,
    reconcile_ops_events,
)
from kicad_mcp.evals.reference_ops_trace import ReferenceOpsTrace


@pytest.fixture(autouse=True)
def _private_test_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / ".dev-tools" / "reference-agent-runs"
    monkeypatch.setattr(reference_ops_trace_validation, "_TRACE_ROOT", root)
    monkeypatch.setattr(reference_ops_reconciliation, "_TRACE_ROOT", root)


def _write_pair(tmp_path: Path) -> tuple[Path, Path]:
    folder = tmp_path / ".dev-tools" / "reference-agent-runs" / "smoke-001"
    folder.mkdir(parents=True, mode=0o700)
    folder.chmod(0o700)
    server = folder / "ops-mcp-trace.jsonl"

    async def record() -> None:
        t = ReferenceOpsTrace(path=server, attempt_id="smoke-001")
        try:
            cid = await t.emit(event_type="tool_call", name="kicad_get_version", status="started")
            await t.emit(
                event_type="tool_result",
                name="kicad_get_version",
                status="completed",
                request_id=cid,
            )
            cid = await t.emit(
                event_type="tool_call", name="kicad_get_server_info", status="started"
            )
            await t.emit(
                event_type="tool_result",
                name="kicad_get_server_info",
                status="failed",
                request_id=cid,
            )
        finally:
            t.close()

    asyncio.run(record())
    rows = [json.loads(line) for line in server.read_text().splitlines()]
    client = folder / "ops-client-observed.jsonl"
    now = datetime.now(UTC) - timedelta(seconds=1)
    events = [
        ReferenceAgentLogEvent(
            attempt_id="smoke-001",
            sequence=i,
            timestamp=now + timedelta(milliseconds=i),
            event_type=row["event_type"],
            name=row["name"],
            status=row["status"],
            details={"provenance": "client_supplied_ops", "request_id": (None if i % 2 else i - 1)},
        ).model_dump(mode="json")
        for i, row in enumerate(rows, start=1)
    ]
    client.write_text("".join(json.dumps(e) + "\n" for e in events))
    client.chmod(0o600)
    return server, client


def test_matching_events_remain_unattested_and_not_benchmark_success(tmp_path: Path) -> None:
    server, client = _write_pair(tmp_path)
    s = reconcile_ops_events(server, client, attempt_id="smoke-001", phase_name="schematic")
    assert s.tool_calls == 2
    assert s.failed_calls == 1
    assert s.status == "client_server_matched_unattested"
    assert s.counts_as_task_success is False
    assert s.client_log_digest.startswith("sha256:")
    assert s.server_log_digest.startswith("sha256:")


@pytest.mark.parametrize(
    "mutation",
    [
        "different-name",
        "status-changed",
        "client-unpaired",
        "wrong-id",
        "fabricated-provenance",
        "extra-detail",
        "missing-newline",
        "open-permissions",
        "extra-event",
        "client-symlink",
        "different-attempt",
    ],
)
def test_rejects_inconsistent_or_untrusted_client_evidence(tmp_path: Path, mutation: str) -> None:
    server, client = _write_pair(tmp_path)
    rows = [json.loads(x) for x in client.read_text().splitlines()]
    if mutation == "different-name":
        rows[2]["name"] = "kicad_get_version"
    elif mutation == "status-changed":
        rows[-1]["status"] = "completed"
    elif mutation == "client-unpaired":
        rows.pop()
    elif mutation == "wrong-id":
        rows[-1]["details"]["request_id"] = 1
    elif mutation == "fabricated-provenance":
        rows[0]["details"]["provenance"] = "server_observed_mcp"
    elif mutation == "extra-detail":
        rows[1]["details"]["payload"] = "file"
    elif mutation == "extra-event":
        rows.extend(rows[-2:])
    elif mutation == "different-attempt":
        rows[0]["attempt_id"] = "smoke-999"
    if mutation not in ("client-symlink", "open-permissions", "missing-newline"):
        client.write_text("".join(json.dumps(r) + "\n" for r in rows))
    elif mutation == "open-permissions":
        if os.name == "nt":
            pytest.skip("POSIX mode enforcement is not applicable on Windows")
        client.chmod(0o644)
    elif mutation == "missing-newline":
        client.write_bytes(client.read_bytes().rstrip(b"\n"))
    elif mutation == "client-symlink":
        other = client.with_name("other-log.jsonl")
        client.rename(other)
        try:
            client.symlink_to(other)
        except OSError:
            pytest.skip("symlink creation is unavailable on this host")
    with pytest.raises(ReferenceOpsReconciliationError):
        reconcile_ops_events(server, client, attempt_id="smoke-001", phase_name="schematic")


def test_server_must_validate_before_client_comparison(tmp_path: Path) -> None:
    server, client = _write_pair(tmp_path)
    server.write_bytes(server.read_bytes().rstrip(b"\n"))
    with pytest.raises(ReferenceOpsReconciliationError):
        reconcile_ops_events(server, client, attempt_id="smoke-001", phase_name="schematic")


def test_refuses_interleaved_client_calls_even_when_tool_names_match(tmp_path: Path) -> None:
    server, client = _write_pair(tmp_path)
    rows = [json.loads(line) for line in client.read_text().splitlines()]
    rows[1], rows[2] = rows[2], rows[1]
    for i, row in enumerate(rows, 1):
        row["sequence"] = i
    client.write_text("".join(json.dumps(row) + "\n" for row in rows))
    with pytest.raises(ReferenceOpsReconciliationError):
        reconcile_ops_events(server, client, attempt_id="smoke-001", phase_name="schematic")

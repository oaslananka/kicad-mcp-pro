"""Codex 0.169.0 app-server lifecycle evidence, not live model execution."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from kicad_mcp.evals import reference_ops_trace_validation
from kicad_mcp.evals.reference_codex_turn_evidence import (
    ReferenceCodexEvidenceError,
    reconcile_codex_turn,
)
from kicad_mcp.evals.reference_ops_trace import ReferenceOpsTrace

BOARD = "stm32f072-usbc"
ATTEMPT = "attempt-004"
THREAD = "thread-fixture"
TURN = "turn-fixture"


def _notification(method: str, **params: object) -> dict[str, Any]:
    return {"method": method, "params": {"threadId": THREAD, **params}}


def _item(method: str, identity: str, tool: str, status: str, offset: int) -> dict[str, Any]:
    return _notification(
        method,
        turnId=TURN,
        item={
            "type": "mcpToolCall",
            "id": identity,
            "server": "kicad",
            "tool": tool,
            "status": status,
            "arguments": {"value": "sk-private-fixture-secret"},
            "result": {"content": [{"type": "text", "text": "/home/private/fixture"}]},
        },
        **{"startedAtMs" if method == "item/started" else "completedAtMs": 1795600000000 + offset},
    )


def _notifications() -> list[dict[str, Any]]:
    return [
        _notification("turn/started", turn={"id": TURN, "status": "inProgress", "items": []}),
        _item("item/started", "first", "kicad_get_version", "inProgress", 1),
        _item("item/completed", "first", "kicad_get_version", "completed", 2),
        _item("item/started", "second", "run_erc", "inProgress", 3),
        _item("item/completed", "second", "run_erc", "failed", 4),
        _notification(
            "turn/completed",
            turn={"id": TURN, "status": "completed", "items": [], "itemsView": "notLoaded"},
        ),
    ]


@pytest.fixture
def trace_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / ".dev-tools/reference-agent-runs"
    monkeypatch.setattr(reference_ops_trace_validation, "_TRACE_ROOT", root)
    parent = root / BOARD / "v1" / ATTEMPT
    parent.mkdir(mode=0o700, parents=True)
    parent.chmod(0o700)
    path = parent / "ops-mcp-trace.jsonl"

    async def record() -> None:
        trace = ReferenceOpsTrace(path=path, attempt_id=ATTEMPT)
        try:
            for name, status in (("kicad_get_version", "completed"), ("run_erc", "failed")):
                request_id = await trace.emit(event_type="tool_call", name=name, status="started")
                await trace.emit(
                    event_type="tool_result", name=name, status=status, request_id=request_id
                )
        finally:
            trace.close()

    asyncio.run(record())
    return path


def _write_client(path: Path, rows: list[dict[str, Any]]) -> Path:
    client = path.with_name("codex-turn-events.jsonl")
    client.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    client.chmod(0o600)
    return client


def _reconcile(path: Path):
    return reconcile_codex_turn(
        path, board_id=BOARD, attempt_id=ATTEMPT, thread_id=THREAD, turn_id=TURN
    )


def test_matching_actual_schema_lifecycle_remains_unattested(trace_path: Path) -> None:
    _write_client(trace_path, _notifications())
    summary = _reconcile(trace_path)
    assert summary.status == "client_server_matched_unattested"
    assert summary.board_id == BOARD
    assert summary.terminal_status == "completed"
    assert summary.tool_calls == 2
    assert summary.failed_calls == 1
    assert summary.counts_as_task_success is False
    assert [event.status for event in summary.events] == [
        "started",
        "completed",
        "started",
        "failed",
    ]
    assert [event.details["request_id"] for event in summary.events] == [None, 1, None, 3]
    assert all(event.details["provenance"] == "client_supplied_codex" for event in summary.events)
    sanitized = "\n".join(event.model_dump_json() for event in summary.events)
    assert "sk-private" not in sanitized
    assert "/home/private" not in sanitized
    assert summary.client_log_digest.startswith("sha256:")
    assert summary.server_log_digest.startswith("sha256:")


@pytest.mark.parametrize("terminal_status", ["failed", "interrupted"])
def test_failed_terminal_is_preserved_not_relabelled(
    trace_path: Path, terminal_status: str
) -> None:
    rows = _notifications()
    rows[-1]["params"]["turn"]["status"] = terminal_status
    rows[-1]["params"]["turn"]["error"] = {"message": "sk-private-provider-error"}
    _write_client(trace_path, rows)
    summary = _reconcile(trace_path)
    assert summary.terminal_status == terminal_status
    assert summary.counts_as_task_success is False
    assert "sk-private" not in repr(summary)


def test_full_terminal_history_must_match_stream(trace_path: Path) -> None:
    rows = _notifications()
    rows[-1]["params"]["turn"].update(
        itemsView="full", items=[rows[2]["params"]["item"], rows[4]["params"]["item"]]
    )
    _write_client(trace_path, rows)
    assert _reconcile(trace_path).tool_calls == 2
    rows[-1]["params"]["turn"]["items"].pop()
    _write_client(trace_path, rows)
    with pytest.raises(ReferenceCodexEvidenceError):
        _reconcile(trace_path)


@pytest.mark.parametrize(
    "mutation",
    [
        "wrong-thread",
        "wrong-turn",
        "missing-start",
        "missing-terminal",
        "duplicate-terminal",
        "duplicate-item",
        "overlapping",
        "completion-without-start",
        "wrong-result-id",
        "wrong-server",
        "unreviewed-tool",
        "mismatched-status",
        "mismatched-name",
        "unfinished",
        "bad-timestamp",
        "timestamp-regression",
        "unexpected-notification",
        "terminal-not-complete",
        "terminal-wrong-id",
        "terminal-hidden-call",
        "extra-after-terminal",
        "command-execution",
        "file-change",
        "web-search",
        "dynamic-tool",
        "sub-agent",
        "unknown-item",
        "terminal-forbidden-item",
    ],
)
def test_rejects_incomplete_or_out_of_contract_execution(trace_path: Path, mutation: str) -> None:
    rows = _notifications()
    if mutation == "wrong-thread":
        rows[1]["params"]["threadId"] = "other-thread"
    elif mutation == "wrong-turn":
        rows[1]["params"]["turnId"] = "other-turn"
    elif mutation == "missing-start":
        rows.pop(0)
    elif mutation == "missing-terminal":
        rows.pop()
    elif mutation == "duplicate-terminal":
        rows.append(rows[-1])
    elif mutation == "duplicate-item":
        rows[3]["params"]["item"]["id"] = "first"
        rows[4]["params"]["item"]["id"] = "first"
    elif mutation == "overlapping":
        rows[2], rows[3] = rows[3], rows[2]
    elif mutation == "completion-without-start":
        rows.pop(1)
    elif mutation == "wrong-result-id":
        rows[2]["params"]["item"]["id"] = "unknown"
    elif mutation == "wrong-server":
        rows[1]["params"]["item"]["server"] = "unreviewed"
    elif mutation == "unreviewed-tool":
        rows[1]["params"]["item"]["tool"] = "pcb_save"
    elif mutation == "mismatched-status":
        rows[4]["params"]["item"]["status"] = "completed"
    elif mutation == "mismatched-name":
        rows[2]["params"]["item"]["tool"] = "run_erc"
    elif mutation == "unfinished":
        rows.pop(4)
    elif mutation == "bad-timestamp":
        rows[1]["params"]["startedAtMs"] = True
    elif mutation == "timestamp-regression":
        rows[2]["params"]["completedAtMs"] = 1000
    elif mutation == "unexpected-notification":
        rows.insert(2, _notification("unknown/notification"))
    elif mutation == "terminal-not-complete":
        rows[-1]["params"]["turn"]["status"] = "inProgress"
    elif mutation == "terminal-wrong-id":
        rows[-1]["params"]["turn"]["id"] = "other-turn"
    elif mutation == "terminal-hidden-call":
        rows[-1]["params"]["turn"]["items"] = [rows[2]["params"]["item"]]
    elif mutation == "extra-after-terminal":
        rows.append(rows[1])
    elif mutation == "terminal-forbidden-item":
        rows[-1]["params"]["turn"].update(
            itemsView="summary", items=[{"id": "hidden", "type": "commandExecution"}]
        )
    else:
        rows[1]["params"]["item"]["type"] = {
            "command-execution": "commandExecution",
            "file-change": "fileChange",
            "web-search": "webSearch",
            "dynamic-tool": "dynamicToolCall",
            "sub-agent": "collabAgentToolCall",
            "unknown-item": "futureTool",
        }[mutation]
    _write_client(trace_path, rows)
    with pytest.raises(ReferenceCodexEvidenceError):
        _reconcile(trace_path)


def test_missing_client_or_incomplete_file_cannot_pass(trace_path: Path) -> None:
    with pytest.raises(ReferenceCodexEvidenceError):
        _reconcile(trace_path)
    client = _write_client(trace_path, _notifications())
    client.write_bytes(client.read_bytes().rstrip(b"\n"))
    with pytest.raises(ReferenceCodexEvidenceError):
        _reconcile(trace_path)


def test_server_trace_must_independently_match(trace_path: Path) -> None:
    _write_client(trace_path, _notifications())
    rows = [json.loads(line) for line in trace_path.read_text().splitlines()]
    rows[2]["name"] = rows[3]["name"] = "kicad_get_server_info"
    trace_path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    with pytest.raises(ReferenceCodexEvidenceError):
        _reconcile(trace_path)


def test_cli_reports_only_matched_metadata(
    trace_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from scripts import reconcile_reference_codex_turn as cli

    _write_client(trace_path, _notifications())
    argv = [
        "--board-id",
        BOARD,
        "--attempt-id",
        ATTEMPT,
        "--thread-id",
        THREAD,
        "--turn-id",
        TURN,
        "--server-trace",
        str(trace_path),
    ]
    assert cli.main(argv) == 0
    output = capsys.readouterr().out
    result = json.loads(output)
    assert result["tool_calls"] == 2
    assert result["terminal_status"] == "completed"
    assert result["counts_as_task_success"] is False
    assert "events" not in result
    assert "sk-private" not in output
    assert str(trace_path) not in output
    assert THREAD not in output
    argv[7] = "foreign-turn"
    assert cli.main(argv) == 2
    assert json.loads(capsys.readouterr().out) == {
        "status": "blocked",
        "counts_as_task_success": False,
    }


def test_symlinked_client_evidence_is_rejected(trace_path: Path) -> None:
    client = _write_client(trace_path, _notifications())
    other = client.with_name("other.jsonl")
    client.rename(other)
    try:
        client.symlink_to(other)
    except OSError:
        pytest.skip("symlink creation unavailable on this platform")
    with pytest.raises(ReferenceCodexEvidenceError):
        _reconcile(trace_path)

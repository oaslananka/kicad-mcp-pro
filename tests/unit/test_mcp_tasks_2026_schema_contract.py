"""Contract guard for the frozen MCP Tasks extension dated 2026-07-28.

Research-only tests. These use the in-memory synthetic ERC/DRC fixture,
never production MCP capability registration, KiCad, or project data.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from tests.research.mcp_tasks_fixture import EXTENSION, TaskFixture


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def call(
    method: str, params: dict[str, Any], *, tasks: bool = True, request_id: int = 1
) -> dict[str, Any]:
    body = dict(params)
    if tasks:
        body["_meta"] = {
            "io.modelcontextprotocol/clientCapabilities": {"extensions": {EXTENSION: {}}}
        }
    return {"jsonrpc": "2.0", "id": request_id, "method": method, "params": body}


def test_frozen_schema_and_independent_client_provenance_is_pinned() -> None:
    source = Path(__file__).resolve().parents[1] / "contracts/mcp/tasks-2026-07-28/provenance.json"
    evidence = json.loads(source.read_text(encoding="utf-8"))
    assert evidence["revision"] == "2026-07-28"
    assert evidence["extension"] == EXTENSION
    assert evidence["schema"]["sha256"] == (
        "bf30afb7ac251e3e22c037b7a685f60ef6603031b5484c0d08b1fa0bbe86d460"
    )
    assert len(evidence["schema"]["upstream_commit"]) == 40
    assert evidence["requester"]["package"] == "@modelcontextprotocol/ext-tasks"
    assert evidence["requester"]["version"] == "0.2.3"
    assert evidence["requester"]["integrity"].startswith("sha512-")


@pytest.mark.parametrize("tool", ["synthetic_erc_review", "synthetic_drc_review"])
def test_only_create_task_uses_task_discriminator(tool: str) -> None:
    fixture = TaskFixture(Clock())
    creation = fixture.dispatch(call("tools/call", {"name": tool, "arguments": {}}), caller="a")
    assert creation["result"]["resultType"] == "task"
    task_id = creation["result"]["taskId"]
    assert set(("createdAt", "lastUpdatedAt", "ttlMs", "pollIntervalMs")).issubset(
        creation["result"]
    )

    reading = fixture.dispatch(call("tasks/get", {"taskId": task_id}), caller="a")
    assert reading["result"]["resultType"] == "complete"
    assert reading["result"]["status"] == "working"
    assert reading["result"]["taskId"] == task_id
    assert "result" not in reading["result"]

    cancelling = fixture.dispatch(call("tasks/cancel", {"taskId": task_id}), caller="a")
    assert cancelling["result"] == {"resultType": "complete"}
    cancelled = fixture.dispatch(call("tasks/get", {"taskId": task_id}), caller="a")
    assert cancelled["result"]["status"] == "cancelled"
    assert "error" not in cancelled["result"]


@pytest.mark.parametrize("method", ["tasks/get", "tasks/update", "tasks/cancel"])
def test_extension_required_response_names_capability(method: str) -> None:
    fixture = TaskFixture(Clock())
    creation = fixture.dispatch(
        call("tools/call", {"name": "synthetic_erc_review", "arguments": {}}),
        caller="a",
    )
    task_id = creation["result"]["taskId"]
    params: dict[str, Any] = {"taskId": task_id}
    if method == "tasks/update":
        params["inputResponses"] = {}
    denied = fixture.dispatch(call(method, params, tasks=False), caller="a")
    assert denied["error"]["code"] == -32021
    assert denied["error"]["data"] == {"requiredCapabilities": {"extensions": {EXTENSION: {}}}}


@pytest.mark.parametrize("legacy_method", ["tasks/list", "tasks/result", "tasks/create"])
def test_frozen_extension_never_accepts_2025_methods(legacy_method: str) -> None:
    fixture = TaskFixture(Clock())
    result = fixture.dispatch(call(legacy_method, {}), caller="a")
    assert result["error"]["code"] == -32601


def test_missing_extension_uses_synchronous_result_without_task_handle() -> None:
    fixture = TaskFixture(Clock())
    legacy = fixture.dispatch(
        call(
            "tools/call",
            {"name": "synthetic_drc_review", "arguments": {}},
            tasks=False,
        ),
        caller="a",
    )
    assert legacy["result"]["resultType"] == "complete"
    assert legacy["result"]["isError"] is False
    assert "taskId" not in legacy["result"]
    assert fixture.retained_count == 0


def test_terminal_tool_error_is_not_protocol_task_failure() -> None:
    fixture = TaskFixture(Clock())
    created = fixture.dispatch(
        call(
            "tools/call",
            {"name": "synthetic_erc_review", "arguments": {"simulateError": True}},
        ),
        caller="a",
    )
    task_id = created["result"]["taskId"]
    fixture.advance(task_id=task_id, caller="a")
    state = fixture.dispatch(call("tasks/get", {"taskId": task_id}), caller="a")
    assert state["result"]["status"] == "completed"
    assert state["result"]["result"]["resultType"] == "complete"
    assert state["result"]["result"]["isError"] is True
    assert "error" not in state["result"]

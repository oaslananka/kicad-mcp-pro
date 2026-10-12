"""Isolated MCP Tasks 2026-07-28 draft protocol probe; NO server integration."""

from __future__ import annotations

from importlib.metadata import version
from typing import Any, cast

import pytest
from mcp import types

from tests.research.mcp_tasks_fixture import (
    EXTENSION,
    MAX_REQUEST_BYTES,
    MAX_TASKS,
    TaskFixture,
)


class ManualClock:
    def __init__(self) -> None:
        self.seconds = 0.0

    def __call__(self) -> float:
        return self.seconds

    def advance(self, seconds: float) -> None:
        self.seconds += seconds


def request(
    method: str,
    *,
    ext: bool = True,
    params: dict[str, Any] | None = None,
    request_id: int = 1,
) -> dict[str, Any]:
    body: dict[str, Any] = dict(params or {})
    if ext:
        body["_meta"] = {
            "io.modelcontextprotocol/clientCapabilities": {"extensions": {EXTENSION: {}}}
        }
    return {"jsonrpc": "2.0", "id": request_id, "method": method, "params": body}


def create(
    fixture: TaskFixture,
    *,
    caller: str = "client-a",
    kind: str = "synthetic_erc_review",
    needs_input: bool = False,
) -> str:
    response = fixture.dispatch(
        request("tools/call", params={"name": kind, "arguments": {"requireInput": needs_input}}),
        caller=caller,
    )
    assert response["result"]["resultType"] == "task"
    return cast(str, response["result"]["taskId"])


def handle(
    fixture: TaskFixture,
    method: str,
    task_id: str,
    *,
    caller: str = "client-a",
    ext: bool = True,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    params = {"taskId": task_id, **(extra or {})}
    return fixture.dispatch(request(method, ext=ext, params=params), caller=caller)


def test_pinned_sdk_keeps_normal_non_task_calls_compatible() -> None:
    assert version("mcp") == "2.2.0"
    source = request(
        "tools/call",
        ext=False,
        params={"name": "synthetic_erc_review", "arguments": {}},
    )
    decoded = types.CallToolRequest.model_validate(source)
    assert decoded.method == "tools/call"
    fixture = TaskFixture(ManualClock())
    result = fixture.dispatch(source, caller="client-a")
    assert result["result"]["resultType"] == "complete"
    assert "taskId" not in result["result"]
    assert fixture.retained_count == 0
    # Actual pinned SDK can parse the ordinary successful CallToolResult payload.
    parsed = types.CallToolResult.model_validate(result["result"])
    assert parsed.is_error is False


def test_negotiated_create_result_is_flat_and_immediately_gettable() -> None:
    clock = ManualClock()
    fixture = TaskFixture(clock)
    task_id = create(fixture)
    assert len(task_id) >= 32
    observed = handle(fixture, "tasks/get", task_id)["result"]
    assert observed["resultType"] == "complete"
    assert observed["status"] == "working"
    assert observed["taskId"] == task_id
    assert observed["ttlMs"] == 60_000
    assert observed["pollIntervalMs"] == 1_000
    assert observed["createdAt"] == observed["lastUpdatedAt"]
    assert observed["createdAt"].endswith("Z")


@pytest.mark.parametrize(
    "capabilities",
    [
        None,
        {},
        {"io.modelcontextprotocol/clientCapabilities": {"extensions": {}}},
        {"io.modelcontextprotocol/clientCapabilities": {"extensions": {EXTENSION: True}}},
        {"io.modelcontextprotocol/clientCapabilities": {"tasks": {}}},
    ],
)
def test_no_per_request_extension_capability_never_issues_handle(
    capabilities: dict[str, Any] | None,
) -> None:
    fixture = TaskFixture(ManualClock())
    call = request(
        "tools/call",
        params={"name": "synthetic_drc_review", "arguments": {}},
        ext=False,
    )
    if capabilities is not None:
        call["params"]["_meta"] = capabilities
    output = fixture.dispatch(call, caller="client-a")
    assert output["result"]["resultType"] == "complete"
    assert fixture.retained_count == 0


@pytest.mark.parametrize("method", ["tasks/get", "tasks/update", "tasks/cancel"])
def test_task_methods_require_extension_on_every_request(method: str) -> None:
    fixture = TaskFixture(ManualClock())
    task_id = create(fixture)
    output = handle(fixture, method, task_id, ext=False)
    assert output["error"]["code"] == -32021


def test_working_polls_are_idempotent_and_do_not_execute_work() -> None:
    fixture = TaskFixture(ManualClock())
    task_id = create(fixture)
    first = handle(fixture, "tasks/get", task_id)
    assert all(handle(fixture, "tasks/get", task_id) == first for _ in range(50))
    assert fixture.retained_count == 1
    fixture.advance(task_id=task_id, caller="client-a")
    completed = handle(fixture, "tasks/get", task_id)["result"]
    assert completed["status"] == "completed"
    assert completed["result"]["isError"] is False
    assert "SYNTHETIC" in completed["result"]["content"][0]["text"]
    assert handle(fixture, "tasks/get", task_id)["result"] == completed


@pytest.mark.parametrize("method", ["tasks/get", "tasks/update", "tasks/cancel"])
def test_cross_caller_and_invalid_handles_never_disclose_state(method: str) -> None:
    fixture = TaskFixture(ManualClock())
    task_id = create(fixture)
    extras: dict[str, Any] | None = {"inputResponses": {}} if method == "tasks/update" else None
    unknown = handle(fixture, method, "unrelated", extra=extras, caller="client-a")
    foreign = handle(fixture, method, task_id, extra=extras, caller="client-b")
    assert foreign == unknown
    assert foreign["error"]["code"] == -32602
    assert task_id not in str(foreign)
    assert handle(fixture, "tasks/get", task_id)["result"]["status"] == "working"


def test_cancel_ack_is_idempotent_and_never_returns_a_task() -> None:
    fixture = TaskFixture(ManualClock())
    task_id = create(fixture)
    ack = handle(fixture, "tasks/cancel", task_id)
    assert ack["result"] == {"resultType": "complete"}
    assert handle(fixture, "tasks/cancel", task_id) == ack
    fixture.advance(task_id=task_id, caller="client-a")
    status = handle(fixture, "tasks/get", task_id)["result"]
    assert status["status"] == "cancelled"
    assert "result" not in status


def test_deadline_transitions_to_protocol_error_without_fake_result() -> None:
    clock = ManualClock()
    fixture = TaskFixture(clock)
    task_id = create(fixture)
    clock.advance(15.1)
    observed = handle(fixture, "tasks/get", task_id)["result"]
    assert observed["status"] == "failed"
    assert observed["error"]["code"] == -32603
    assert "result" not in observed
    fixture.advance(task_id=task_id, caller="client-a")
    assert handle(fixture, "tasks/get", task_id)["result"] == observed


def test_ttl_purges_task_and_releases_capacity() -> None:
    clock = ManualClock()
    fixture = TaskFixture(clock)
    task_id = create(fixture)
    clock.advance(60)
    assert handle(fixture, "tasks/get", task_id)["error"]["code"] == -32602
    assert fixture.retained_count == 0
    assert create(fixture) != task_id


def test_restart_loses_fixture_task_with_fail_closed_error() -> None:
    clock = ManualClock()
    task_id = create(TaskFixture(clock))
    restarted = TaskFixture(clock)
    assert handle(restarted, "tasks/get", task_id)["error"]["code"] == -32602


def test_pending_input_update_handles_duplicates_and_unknown_keys() -> None:
    fixture = TaskFixture(ManualClock())
    task_id = create(fixture, needs_input=True)
    fixture.advance(task_id=task_id, caller="client-a")
    observed = handle(fixture, "tasks/get", task_id)["result"]
    assert observed["status"] == "input_required"
    assert set(observed["inputRequests"]) == {"confirm"}
    # Duplicate polling does not regenerate requests.
    assert handle(fixture, "tasks/get", task_id)["result"] == observed
    ignored = handle(
        fixture,
        "tasks/update",
        task_id,
        extra={"inputResponses": {"unknown": {"action": "accept"}}},
    )
    assert ignored["result"] == {"resultType": "complete"}
    assert handle(fixture, "tasks/get", task_id)["result"] == observed
    ack = handle(
        fixture,
        "tasks/update",
        task_id,
        extra={"inputResponses": {"confirm": {"action": "accept", "content": {"ack": True}}}},
    )
    assert ack["result"] == {"resultType": "complete"}
    assert handle(fixture, "tasks/update", task_id, extra={"inputResponses": {}}) == ack
    assert handle(fixture, "tasks/get", task_id)["result"]["status"] == "working"
    fixture.advance(task_id=task_id, caller="client-a")
    assert handle(fixture, "tasks/get", task_id)["result"]["status"] == "completed"


@pytest.mark.parametrize(
    "method", ["tasks/list", "tasks/result", "tasks/create", "resources/read", "tools/list"]
)
def test_fixture_does_not_expose_legacy_or_extra_methods(method: str) -> None:
    fixture = TaskFixture(ManualClock())
    assert fixture.dispatch(request(method), caller="client-a")["error"]["code"] == -32601


@pytest.mark.parametrize(
    "name,arguments",
    [
        ("pcb_mutate", {}),
        ("synthetic_erc_review", {"projectPath": "/secret"}),
        ("synthetic_drc_review", {"write": True}),
        ("synthetic_drc_review", {"requireInput": "yes"}),
        ("synthetic_erc_review", {"requireInput": 1}),
    ],
)
def test_no_project_input_write_tool_or_unrecognized_argument(
    name: str, arguments: dict[str, Any]
) -> None:
    fixture = TaskFixture(ManualClock())
    response = fixture.dispatch(
        request("tools/call", params={"name": name, "arguments": arguments}), caller="client-a"
    )
    assert response["error"]["code"] == -32602
    assert fixture.retained_count == 0


def test_unhashable_tool_name_is_rejected_as_invalid_params() -> None:
    fixture = TaskFixture(ManualClock())
    result = fixture.dispatch(
        request("tools/call", params={"name": [], "arguments": {}}), caller="client-a"
    )
    assert result["error"]["code"] == -32602
    assert fixture.retained_count == 0


def test_fixed_capacity_bounded_message_and_invalid_principal() -> None:
    fixture = TaskFixture(ManualClock())
    task_ids = {create(fixture) for _ in range(MAX_TASKS)}
    assert len(task_ids) == MAX_TASKS
    full = fixture.dispatch(
        request("tools/call", params={"name": "synthetic_erc_review", "arguments": {}}),
        caller="client-a",
    )
    assert full["error"]["code"] == -32000
    oversized = fixture.dispatch(
        request(
            "tools/call",
            params={
                "name": "synthetic_erc_review",
                "arguments": {"injected": "x" * MAX_REQUEST_BYTES},
            },
        ),
        caller="client-a",
    )
    assert oversized["error"]["code"] == -32600
    malformed_owner = fixture.dispatch(
        request("tasks/get", params={"taskId": next(iter(task_ids))}), caller=""
    )
    assert malformed_owner["error"]["code"] == -32600


def test_tool_result_errors_are_completed_not_failed() -> None:
    fixture = TaskFixture(ManualClock())
    response = fixture.dispatch(
        request(
            "tools/call",
            params={"name": "synthetic_erc_review", "arguments": {"simulateError": True}},
        ),
        caller="client-a",
    )
    task_id = cast(str, response["result"]["taskId"])
    fixture.advance(task_id=task_id, caller="client-a")
    observed = handle(fixture, "tasks/get", task_id)["result"]
    assert observed["status"] == "completed"
    assert observed["result"]["isError"] is True
    assert "error" not in observed


def test_existing_production_2026_capability_fixtures_do_not_advertise_tasks() -> None:
    import json
    from pathlib import Path

    base = Path(__file__).resolve().parents[1] / "contracts/mcp/2026-07-28"
    for filename in ("server-discover.response.json", "tools-list.response.json"):
        text = (base / filename).read_text(encoding="utf-8")
        payload = json.loads(text)
        assert EXTENSION not in text
        assert payload["result"]["resultType"] == "complete"

"""Disposable MCP Tasks draft wire-model: synthetic read-only ERC/DRC ONLY.

This is a hermetic protocol fixture, NOT an MCP server extension or KiCad runner.
No filesystem, sockets, subprocesses, worker threads, project data or secrets.
"""

from __future__ import annotations

import json
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

EXTENSION = "io.modelcontextprotocol/tasks"
MAX_TASKS = 8
MAX_REQUEST_BYTES = 4096
TTL_MS = 60_000
DEADLINE_SECONDS = 15
POLL_INTERVAL_MS = 1_000
KINDS = frozenset({"synthetic_erc_review", "synthetic_drc_review"})
_BASE = datetime(2026, 7, 28, tzinfo=UTC)


def _timestamp(seconds: float) -> str:
    return (_BASE + timedelta(seconds=seconds)).isoformat().replace("+00:00", "Z")


@dataclass
class _Task:
    owner: str
    kind: str
    task_id: str
    created: float
    updated: float
    status: str = "working"
    requires_input: bool = False
    simulate_error: bool = False
    input_received: bool = False
    error: dict[str, object] | None = None
    result: dict[str, object] | None = None


class TaskFixture:
    """Per-caller bounded in-memory state; caller identity comes from transport."""

    def __init__(self, clock: Callable[[], float]) -> None:
        self._clock = clock
        self._tasks: dict[str, _Task] = {}

    @property
    def retained_count(self) -> int:
        return len(self._tasks)

    def _purge(self) -> None:
        now = self._clock()
        for task_id, task in tuple(self._tasks.items()):
            if now >= task.created + TTL_MS / 1000:
                del self._tasks[task_id]

    def _lookup(self, task_id: object, caller: str) -> _Task | None:
        self._purge()
        if not isinstance(task_id, str) or len(task_id) > 128:
            return None
        task = self._tasks.get(task_id)
        if task is None or task.owner != caller:
            return None
        if task.status in {"working", "input_required"} and (
            self._clock() >= task.created + DEADLINE_SECONDS
        ):
            task.status = "failed"
            task.error = {"code": -32603, "message": "Synthetic task deadline exceeded"}
            task.updated = self._clock()
        return task

    @staticmethod
    def _supports_tasks(params: dict[str, Any]) -> bool:
        meta = params.get("_meta")
        if not isinstance(meta, dict):
            return False
        capabilities = meta.get("io.modelcontextprotocol/clientCapabilities")
        if not isinstance(capabilities, dict):
            return False
        extensions = capabilities.get("extensions")
        return isinstance(extensions, dict) and isinstance(extensions.get(EXTENSION), dict)

    @staticmethod
    def _error(request_id: object, code: int, message: str) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}

    @staticmethod
    def _reply(request_id: object, result: dict[str, object]) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": request_id, "result": result}

    @staticmethod
    def _summary(kind: str) -> dict[str, Any]:
        return {
            "content": [{"type": "text", "text": f"SYNTHETIC {kind}: zero real designs analyzed"}],
            "isError": False,
        }

    def _view(self, task: _Task, *, creation: bool = False) -> dict[str, Any]:
        response: dict[str, object] = {
            "resultType": "task" if creation else "complete",
            "taskId": task.task_id,
            "status": task.status,
            "createdAt": _timestamp(task.created),
            "lastUpdatedAt": _timestamp(task.updated),
            "ttlMs": TTL_MS,
            "pollIntervalMs": POLL_INTERVAL_MS,
        }
        if not creation:
            if task.status == "completed":
                response["result"] = task.result
            elif task.status == "failed":
                response["error"] = task.error
            elif task.status == "input_required":
                response["inputRequests"] = {
                    "confirm": {
                        "method": "elicitation/create",
                        "params": {
                            "mode": "form",
                            "message": (
                                "Acknowledge synthetic review; no real analysis is performed"
                            ),
                            "requestedSchema": {
                                "type": "object",
                                "properties": {"ack": {"type": "boolean"}},
                                "required": ["ack"],
                            },
                        },
                    }
                }
        return response

    def dispatch(self, request: dict[str, Any], *, caller: str) -> dict[str, Any]:
        """Handle only draft probe messages; caller is trusted transport-supplied."""
        request_id = request.get("id")
        if (
            not isinstance(caller, str)
            or not 1 <= len(caller) <= 128
            or request.get("jsonrpc") != "2.0"
            or not isinstance(request_id, (str, int))
            or len(json.dumps(request)) > MAX_REQUEST_BYTES
        ):
            return self._error(request_id, -32600, "Invalid or oversized request")
        method = request.get("method")
        params = request.get("params")
        if not isinstance(params, dict):
            return self._error(request_id, -32602, "Invalid params")
        enabled = self._supports_tasks(params)
        if method == "tools/call":
            kind = params.get("name")
            args = params.get("arguments")
            if (
                not isinstance(kind, str)
                or kind not in KINDS
                or not isinstance(args, dict)
                or (set(args) - {"requireInput", "simulateError"})
                or not isinstance(args.get("requireInput", False), bool)
                or not isinstance(args.get("simulateError", False), bool)
            ):
                return self._error(request_id, -32602, "Read-only synthetic tool required")
            if not enabled:
                return self._reply(request_id, {"resultType": "complete", **self._summary(kind)})
            self._purge()
            if len(self._tasks) >= MAX_TASKS:
                return self._error(request_id, -32000, "Synthetic task capacity exhausted")
            now = self._clock()
            task_id = secrets.token_urlsafe(24)
            task = _Task(
                owner=caller,
                kind=kind,
                task_id=task_id,
                created=now,
                updated=now,
                requires_input=args.get("requireInput") is True,
                simulate_error=args.get("simulateError") is True,
            )
            self._tasks[task_id] = task
            return self._reply(request_id, self._view(task, creation=True))
        if method not in ("tasks/get", "tasks/update", "tasks/cancel"):
            return self._error(request_id, -32601, "Method not found")
        if not enabled:
            return self._error(request_id, -32021, "Missing required client capability")
        existing = self._lookup(params.get("taskId"), caller)
        if existing is None:
            return self._error(request_id, -32602, "Task not found")
        if method == "tasks/get":
            return self._reply(request_id, self._view(existing))
        if method == "tasks/cancel":
            if existing.status in {"working", "input_required"}:
                existing.status = "cancelled"
                existing.updated = self._clock()
            return self._reply(request_id, {"resultType": "complete"})
        responses = params.get("inputResponses")
        if not isinstance(responses, dict) or len(responses) > 8:
            return self._error(request_id, -32602, "Invalid inputResponses")
        if existing.status == "input_required" and "confirm" in responses:
            value = responses["confirm"]
            if (
                isinstance(value, dict)
                and value.get("action") == "accept"
                and value.get("content") == {"ack": True}
            ):
                existing.input_received = True
                existing.status = "working"
                existing.updated = self._clock()
        return self._reply(request_id, {"resultType": "complete"})

    def advance(self, *, task_id: str, caller: str) -> None:
        """Explicit synthetic worker step, not a wire method or background worker."""
        task = self._lookup(task_id, caller)
        if task is None or task.status != "working":
            return
        if task.requires_input and not task.input_received:
            task.status = "input_required"
        else:
            task.status = "completed"
            task.result = self._summary(task.kind)
            if task.simulate_error:
                task.result = {
                    "content": [{"type": "text", "text": "SYNTHETIC read-only tool error"}],
                    "isError": True,
                }
        task.updated = self._clock()

"""Task manager for the experimental MCP Tasks extension draft surface.

The MCP Tasks protocol enables servers to expose long-running operations
as trackable ``Task`` objects with status polling and cancellation.

.. warning::

    The task protocol surface is experimental/draft and may change
    before reaching Final. This implementation is opt-in behind the
    ``KICAD_MCP_ENABLE_TASKS`` flag and is **not** advertised via
    ``supportedMcpProtocolVersions``.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from mcp.types import (
    CancelTaskResult,
    GetTaskResult,
    Task,
    TaskStatus,
    TaskStatusNotification,
    TaskStatusNotificationParams,
)

_TASK_DEFAULT_TTL_S = 3600  # 1 hour
_TASK_DEFAULT_POLL_INTERVAL_S = 2

# Re-export task status literal for use by tool wrappers
TaskStatusType = TaskStatus


class _TaskRecord:
    """Internal mutable state backing a single tracked task."""

    def __init__(
        self,
        task_id: str,
        description: str,
        ttl_s: int = _TASK_DEFAULT_TTL_S,
        poll_interval_s: int = _TASK_DEFAULT_POLL_INTERVAL_S,
        timeout_s: float | None = None,
    ) -> None:
        self.task_id = task_id
        self.description = description
        self.status: TaskStatus = "working"
        self.status_message: str | None = None
        self.created_at = datetime.now(UTC)
        self.last_updated_at = self.created_at
        self.ttl_s = ttl_s
        self.poll_interval_s = poll_interval_s
        # Optional wall-clock execution budget. None = no timeout (default).
        self.timeout_s = timeout_s
        self._cancel_event = asyncio.Event()
        self._finished_event = asyncio.Event()
        # Handle to the background runner so cancel() can truly interrupt it.
        self._runner: asyncio.Task[Any] | None = None
        self._result: Any = None
        self._error: str | None = None

    def to_task(self) -> Task:
        """Render the current state as an MCP ``Task`` object."""
        return Task(
            taskId=self.task_id,
            status=self.status,
            statusMessage=self.status_message,
            createdAt=self.created_at,
            lastUpdatedAt=self.last_updated_at,
            ttl=self.ttl_s,
            pollInterval=self.poll_interval_s,
        )

    def to_get_result(self, meta: dict[str, Any] | None = None) -> GetTaskResult:
        """Render the current state as a ``GetTaskResult``."""
        return GetTaskResult(
            taskId=self.task_id,
            status=self.status,
            statusMessage=self.status_message,
            createdAt=self.created_at,
            lastUpdatedAt=self.last_updated_at,
            ttl=self.ttl_s,
            pollInterval=self.poll_interval_s,
            meta=meta,
        )

    def to_cancel_result(self, meta: dict[str, Any] | None = None) -> CancelTaskResult:
        """Render the current state as a ``CancelTaskResult``."""
        return CancelTaskResult(
            taskId=self.task_id,
            status=self.status,
            statusMessage=self.status_message,
            createdAt=self.created_at,
            lastUpdatedAt=self.last_updated_at,
            ttl=self.ttl_s,
            pollInterval=self.poll_interval_s,
            meta=meta,
        )

    def mark(
        self,
        status: TaskStatus,
        message: str | None = None,
    ) -> None:
        """Transition the task to a new status."""
        self.status = status
        self.last_updated_at = datetime.now(UTC)
        if message is not None:
            self.status_message = message

    def finish(self, result: Any = None, error: str | None = None) -> None:  # noqa: ANN401
        """Mark the task as completed or failed."""
        if error is not None:
            self.mark("failed", message=error)
            self._error = error
        else:
            self.mark("completed", message="Task completed successfully.")
            self._result = result
        self._finished_event.set()

    @property
    def cancelled(self) -> bool:
        return self._cancel_event.is_set()

    @property
    def finished(self) -> bool:
        return self._finished_event.is_set()


class TaskManager:
    """Manage the lifecycle of MCP Tasks within the server.

    Thread-safe: all public methods use a single lock, and the background
    runner is async-safe.
    """

    def __init__(self) -> None:
        self._tasks: dict[str, _TaskRecord] = {}
        self._lock = asyncio.Lock()
        self._cleanup_task: asyncio.Task[None] | None = None

    # ------------------------------------------------------------------
    # Payload helpers
    # ------------------------------------------------------------------

    async def get_result_text(self, task_id: str) -> str | None:
        """Return the text payload of a completed task (for GetTaskPayloadRequest)."""
        record = await self._get_record(task_id)
        if record is None or record.status not in ("completed", "failed", "cancelled"):
            return None
        if record._error is not None:
            return f"Task failed: {record._error}"
        if record._result is not None:
            # Try common serialization paths
            if hasattr(record._result, "text"):
                return str(record._result.text)
            if isinstance(record._result, str):
                return record._result
            return str(record._result)
        return None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(
        self,
        description: str,
        ttl_s: int | None = None,
        timeout_s: float | None = None,
    ) -> Task:
        """Create a new task in ``working`` state and return its MCP ``Task`` descriptor."""
        task_id = str(uuid4())
        record = _TaskRecord(
            task_id=task_id,
            description=description,
            ttl_s=_TASK_DEFAULT_TTL_S if ttl_s is None else ttl_s,
            timeout_s=timeout_s,
        )
        async with self._lock:
            self._tasks[task_id] = record
        return record.to_task()

    async def run_and_wait(
        self,
        description: str,
        coro_factory: Callable[[], Awaitable[Any]],
        ttl_s: int | None = None,
        timeout_s: float | None = None,
    ) -> Task:
        """Create a task, execute the coroutine in the background, and return the task descriptor.

        The caller should poll ``tasks/get`` to check completion or failure. When
        ``timeout_s`` is set the work is bounded by that wall-clock budget and fails
        with a timeout if it overruns. The background runner handle is recorded so
        ``cancel()`` can truly interrupt the coroutine, not just flip the status.
        """
        task = await self.start(description, ttl_s=ttl_s, timeout_s=timeout_s)
        record = await self._get_record(task.taskId)
        runner = asyncio.ensure_future(self._run(task.taskId, coro_factory))
        # No await between ensure_future and this assignment, so the runner handle
        # is in place before _run can execute — cancel() can always reach it.
        if record is not None:
            record._runner = runner
        return task

    async def _run(
        self,
        task_id: str,
        coro_factory: Callable[[], Awaitable[Any]],
    ) -> None:
        """Background runner: executes the coroutine and updates the task record."""
        record = await self._get_record(task_id)
        if record is None:
            return
        try:
            if record.timeout_s is not None:
                result = await asyncio.wait_for(coro_factory(), timeout=record.timeout_s)
            else:
                result = await coro_factory()
            if not record.cancelled:
                record.finish(result=result)
        except TimeoutError:
            if not record.cancelled:
                record.finish(error=f"Task exceeded its {record.timeout_s}s timeout.")
        except asyncio.CancelledError:
            if not record.finished:
                record.mark("cancelled", message="Task was cancelled.")
                record._finished_event.set()
            raise
        except Exception as exc:
            if not record.cancelled:
                record.finish(error=f"{type(exc).__name__}: {exc}")
            elif not record.finished:
                record.mark("cancelled", message="Task was cancelled.")
                record._finished_event.set()

    async def cancel(self, task_id: str) -> CancelTaskResult | None:
        """Request cancellation of a running task.

        Returns the ``CancelTaskResult`` if the task exists, or ``None`` if the
        task ID is unknown.
        """
        async with self._lock:
            record = self._tasks.get(task_id)
            if record is None:
                return None
            if record.finished or record.status in ("completed", "failed", "cancelled"):
                return record.to_cancel_result()
            record._cancel_event.set()
            record.mark("cancelled", message="Cancellation requested.")
            record._finished_event.set()
            runner = record._runner
        # Interrupt the running coroutine itself (cancel() is non-blocking), so a
        # long operation actually stops instead of leaking until it finishes.
        if runner is not None and not runner.done():
            runner.cancel()
        return record.to_cancel_result()

    async def get(self, task_id: str) -> GetTaskResult | None:
        """Return the current state of a task, or ``None`` if unknown."""
        record = await self._get_record(task_id)
        if record is None:
            return None
        return record.to_get_result()

    async def list_tasks(self) -> list[Task]:
        """Return all non-expired tasks."""
        await self._evict_expired()
        async with self._lock:
            return [rec.to_task() for rec in self._tasks.values()]

    # ------------------------------------------------------------------
    # Notification helpers
    # ------------------------------------------------------------------

    def status_notification(self, task_id: str) -> TaskStatusNotification | None:
        """Build a ``TaskStatusNotification`` for the given task, or ``None``."""
        record = self._tasks.get(task_id)
        if record is None:
            return None
        return TaskStatusNotification(
            params=TaskStatusNotificationParams(
                taskId=record.task_id,
                status=record.status,
                statusMessage=record.status_message,
                createdAt=record.created_at,
                lastUpdatedAt=record.last_updated_at,
                ttl=record.ttl_s,
                pollInterval=record.poll_interval_s,
            )
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _get_record(self, task_id: str) -> _TaskRecord | None:
        async with self._lock:
            return self._tasks.get(task_id)

    async def _evict_expired(self) -> None:
        """Remove tasks that have exceeded their TTL."""
        now = datetime.now(UTC)
        async with self._lock:
            expired = [
                tid
                for tid, rec in self._tasks.items()
                if rec.last_updated_at + timedelta(seconds=rec.ttl_s) < now
            ]
            for tid in expired:
                del self._tasks[tid]

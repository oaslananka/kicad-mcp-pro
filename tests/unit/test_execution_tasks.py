"""Unit tests for TaskManager and _TaskRecord."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from kicad_mcp.execution.tasks import TaskManager, TaskStatusType

# =========================================================================
# _TaskRecord lifecycle
# =========================================================================


async def test_create_task_defaults() -> None:
    tm = TaskManager()
    task = await tm.start("test description", ttl_s=60)
    assert task.taskId is not None
    assert task.status == "working"
    assert task.statusMessage is None
    assert task.createdAt is not None
    assert task.lastUpdatedAt is not None
    assert task.ttl == 60
    assert task.pollInterval is not None


async def test_create_multiple_tasks_have_unique_ids() -> None:
    tm = TaskManager()
    t1 = await tm.start("first", ttl_s=60)
    t2 = await tm.start("second", ttl_s=60)
    assert t1.taskId != t2.taskId


# =========================================================================
# get()
# =========================================================================


async def test_get_unknown_task_returns_none() -> None:
    tm = TaskManager()
    result = await tm.get("nonexistent-id")
    assert result is None


async def test_get_known_task_returns_state() -> None:
    tm = TaskManager()
    task = await tm.start("get-test", ttl_s=60)
    result = await tm.get(task.taskId)
    assert result is not None
    assert result.taskId == task.taskId
    assert result.status == "working"


async def test_get_after_cancel_shows_cancelled() -> None:
    tm = TaskManager()
    task = await tm.start("cancel-test", ttl_s=60)
    await tm.cancel(task.taskId)
    result = await tm.get(task.taskId)
    assert result is not None
    assert result.status == "cancelled"


# =========================================================================
# list_tasks()
# =========================================================================


async def test_list_tasks_empty_initially() -> None:
    tm = TaskManager()
    tasks = await tm.list_tasks()
    assert tasks == []


async def test_list_tasks_returns_all_active() -> None:
    tm = TaskManager()
    t1 = await tm.start("a", ttl_s=60)
    t2 = await tm.start("b", ttl_s=60)
    tasks = await tm.list_tasks()
    assert len(tasks) == 2
    ids = {t.taskId for t in tasks}
    assert ids == {t1.taskId, t2.taskId}


async def test_list_tasks_evicts_expired() -> None:
    tm = TaskManager()
    task = await tm.start("expired", ttl_s=1)
    # Artificially age the record so it's past TTL
    rec = await tm._get_record(task.taskId)
    assert rec is not None
    rec.last_updated_at = datetime.now(UTC) - timedelta(seconds=2)
    tasks = await tm.list_tasks()
    assert task.taskId not in {t.taskId for t in tasks}


# =========================================================================
# cancel()
# =========================================================================


async def test_cancel_unknown_returns_none() -> None:
    tm = TaskManager()
    result = await tm.cancel("nonexistent-id")
    assert result is None


async def test_cancel_changes_status() -> None:
    tm = TaskManager()
    task = await tm.start("will-cancel", ttl_s=60)
    result = await tm.cancel(task.taskId)
    assert result is not None
    assert result.taskId == task.taskId
    assert result.status == "cancelled"
    assert "Cancellation" in (result.statusMessage or "")


async def test_cancel_already_completed_is_idempotent() -> None:
    tm = TaskManager()
    task = await tm.start("will-finish", ttl_s=60)
    rec = await tm._get_record(task.taskId)
    assert rec is not None
    rec.finish(result="done")
    result = await tm.cancel(task.taskId)
    assert result is not None
    assert result.status == "completed"


async def test_cancel_twice_is_idempotent() -> None:
    tm = TaskManager()
    task = await tm.start("double-cancel", ttl_s=60)
    r1 = await tm.cancel(task.taskId)
    r2 = await tm.cancel(task.taskId)
    assert r1 is not None and r2 is not None
    assert r1.status == "cancelled"
    assert r2.status == "cancelled"


# =========================================================================
# run_and_wait() — background execution
# =========================================================================


async def test_run_and_wait_completes_successfully() -> None:
    tm = TaskManager()

    async def work() -> str:
        await asyncio.sleep(0.05)
        return "done"

    task = await tm.run_and_wait("background-work", work, ttl_s=60)
    assert task.status == "working"

    # Poll until completion
    for _ in range(50):
        result = await tm.get(task.taskId)
        assert result is not None
        if result.status == "completed":
            assert result.statusMessage == "Task completed successfully."
            return
        await asyncio.sleep(0.02)
    pytest.fail("Task did not complete in time")


async def test_run_and_wait_captures_exception() -> None:
    tm = TaskManager()

    async def failing() -> str:
        await asyncio.sleep(0.05)
        msg = "something broke"
        raise ValueError(msg)

    task = await tm.run_and_wait("failing-work", failing, ttl_s=60)
    for _ in range(50):
        result = await tm.get(task.taskId)
        assert result is not None
        if result.status == "failed":
            assert "ValueError" in (result.statusMessage or "")
            return
        await asyncio.sleep(0.02)
    pytest.fail("Task did not fail in time")


async def test_run_and_wait_cancellation_stops_execution() -> None:
    tm = TaskManager()
    started = asyncio.Event()

    async def cancellable_work() -> str:
        started.set()
        await asyncio.sleep(10)  # long sleep - should be cancelled
        return "never"

    task = await tm.run_and_wait("cancellable", cancellable_work, ttl_s=60)
    await started.wait()  # ensure the work coroutine is running
    await tm.cancel(task.taskId)

    for _ in range(50):
        result = await tm.get(task.taskId)
        assert result is not None
        if result.status == "cancelled":
            return
        await asyncio.sleep(0.02)
    pytest.fail("Task was not cancelled in time")


async def test_cancellation_actually_interrupts_the_coroutine() -> None:
    # P5-T5: cancel() must interrupt the running coroutine, not just flip the
    # record's status while the work leaks on in the background.
    tm = TaskManager()
    started = asyncio.Event()
    interrupted = asyncio.Event()

    async def work() -> str:
        started.set()
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            interrupted.set()
            raise
        return "never"

    task = await tm.run_and_wait("interruptible", work, ttl_s=60)
    await started.wait()
    await tm.cancel(task.taskId)

    # The coroutine itself received CancelledError — proves real interruption.
    await asyncio.wait_for(interrupted.wait(), timeout=1.0)
    result = await tm.get(task.taskId)
    assert result is not None
    assert result.status == "cancelled"


async def test_run_and_wait_enforces_execution_timeout() -> None:
    # P5-T5: a task that overruns its timeout fails instead of hanging forever.
    tm = TaskManager()

    async def slow() -> str:
        await asyncio.sleep(10)
        return "never"

    task = await tm.run_and_wait("slow", slow, ttl_s=60, timeout_s=0.05)
    for _ in range(50):
        result = await tm.get(task.taskId)
        assert result is not None
        if result.status == "failed":
            assert "timeout" in (result.statusMessage or "").lower()
            return
        await asyncio.sleep(0.02)
    pytest.fail("Task did not time out in time")


# =========================================================================
# Concurrent tasks
# =========================================================================


async def test_concurrent_tasks_all_complete() -> None:
    tm = TaskManager()

    async def slow(value: str) -> str:
        await asyncio.sleep(0.1)
        return value

    t1 = await tm.run_and_wait("c1", lambda: slow("a"), ttl_s=60)
    t2 = await tm.run_and_wait("c2", lambda: slow("b"), ttl_s=60)

    for _ in range(100):
        r1 = await tm.get(t1.taskId)
        r2 = await tm.get(t2.taskId)
        assert r1 is not None and r2 is not None
        if r1.status == "completed" and r2.status == "completed":
            return
        await asyncio.sleep(0.02)
    pytest.fail("Concurrent tasks did not both complete in time")


# =========================================================================
# status_notification()
# =========================================================================


async def test_status_notification_unknown_returns_none() -> None:
    tm = TaskManager()
    notif = tm.status_notification("nonexistent")
    assert notif is None


async def test_status_notification_returns_valid_payload() -> None:
    tm = TaskManager()
    task = await tm.start("notif-test", ttl_s=60)
    notif = tm.status_notification(task.taskId)
    assert notif is not None
    assert notif.params.taskId == task.taskId
    assert notif.params.status == "working"


# =========================================================================
# Re-export
# =========================================================================


def test_task_status_type_is_re_exported() -> None:
    from kicad_mcp.execution import TaskStatusType as Exported

    assert Exported is TaskStatusType


async def test_task_runner_preserves_cancelled_state() -> None:
    tm = TaskManager()
    started = asyncio.Event()

    async def work() -> None:
        started.set()
        await asyncio.sleep(10)

    task = await tm.run_and_wait("cancel-propagation", work, ttl_s=60)
    await started.wait()
    record = await tm._get_record(task.taskId)
    assert record is not None
    runner = record._runner
    assert runner is not None

    await tm.cancel(task.taskId)
    with pytest.raises(asyncio.CancelledError):
        await runner
    assert runner.cancelled()

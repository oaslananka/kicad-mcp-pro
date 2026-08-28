"""Unit tests for the centralized KiCad IPC command queue (issue #158).

These exercise retry classification, idempotency, journaling and serialization with
fake transports/clocks, so they run without a live KiCad.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

import pytest

from kicad_mcp.ipc.command_queue import (
    KiCadCommandQueue,
    RetryClass,
    classify_error,
    get_command_queue,
    reset_command_queue,
)
from kicad_mcp.ipc.errors import KiCadIpcBusyError, KiCadIpcTimeoutError


class _RetryableError(Exception):
    retryable = True
    code = "RETRY"


class _FatalError(Exception):
    retryable = False
    code = "FATAL"


def _fake_clock() -> Callable[[], float]:
    state = {"t": 0.0}

    def now() -> float:
        state["t"] += 1.0
        return state["t"]

    return now


def _queue(**kwargs: object) -> KiCadCommandQueue:
    slept: list[float] = []
    defaults: dict[str, object] = {
        "sleep": slept.append,
        "time_fn": _fake_clock(),
    }
    defaults.update(kwargs)
    queue = KiCadCommandQueue(**defaults)  # type: ignore[arg-type]
    queue._slept = slept  # type: ignore[attr-defined]
    return queue


def test_classify_error() -> None:
    assert classify_error(_RetryableError()) is RetryClass.RETRYABLE
    assert classify_error(KiCadIpcBusyError("busy")) is RetryClass.RETRYABLE
    assert classify_error(_FatalError()) is RetryClass.NON_RETRYABLE
    assert classify_error(ValueError("x")) is RetryClass.NON_RETRYABLE
    assert classify_error(TimeoutError()) is RetryClass.TIMEOUT
    assert classify_error(KiCadIpcTimeoutError("late")) is RetryClass.TIMEOUT


def test_success_runs_once_and_journals() -> None:
    queue = _queue()
    calls = {"n": 0}

    def command() -> str:
        calls["n"] += 1
        return "ok"

    result = queue.execute("move_footprint", command, correlation_id="call-1")
    assert result == "ok"
    assert calls["n"] == 1
    assert len(queue.journal) == 1
    assert queue.journal[0].status == "success"
    assert queue.journal[0].attempts == 1


def test_retryable_error_is_retried_then_succeeds() -> None:
    queue = _queue(max_retries=3)
    attempts = {"n": 0}

    def command() -> str:
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise _RetryableError("transient")
        return "done"

    result = queue.execute("op", command, correlation_id="c")
    assert result == "done"
    assert attempts["n"] == 3
    assert queue.journal[-1].status == "success"
    assert queue.journal[-1].attempts == 3
    # Backoff sleeps happened between the two retries.
    assert queue._slept == [queue.backoff_delay(1), queue.backoff_delay(2)]  # type: ignore[attr-defined]


def test_retryable_error_exhausts_and_raises() -> None:
    queue = _queue(max_retries=2)

    def command() -> str:
        raise _RetryableError("always")

    with pytest.raises(_RetryableError):
        queue.execute("op", command, correlation_id="c")
    entry = queue.journal[-1]
    assert entry.status == "failed"
    assert entry.attempts == 3  # initial + 2 retries
    assert entry.error_code == "RETRY"


def test_non_retryable_error_is_not_retried() -> None:
    queue = _queue(max_retries=5)
    attempts = {"n": 0}

    def command() -> str:
        attempts["n"] += 1
        raise _FatalError("nope")

    with pytest.raises(_FatalError):
        queue.execute("op", command)
    assert attempts["n"] == 1
    assert queue.journal[-1].status == "failed"
    assert queue._slept == []  # type: ignore[attr-defined]


def test_timeout_is_treated_as_retryable() -> None:
    queue = _queue(max_retries=1)
    attempts = {"n": 0}

    def command() -> str:
        attempts["n"] += 1
        raise TimeoutError("slow")

    with pytest.raises(TimeoutError):
        queue.execute("op", command)
    assert attempts["n"] == 2  # retried once


def test_idempotency_deduplicates() -> None:
    queue = _queue()
    calls = {"n": 0}

    def command() -> int:
        calls["n"] += 1
        return 42

    first = queue.execute("op", command, idempotency_key="k1")
    second = queue.execute("op", command, idempotency_key="k1")
    assert first == second == 42
    assert calls["n"] == 1
    statuses = [e.status for e in queue.journal]
    assert statuses == ["success", "deduplicated"]


def test_journal_correlation_by_call_id() -> None:
    queue = _queue()
    queue.execute("a", lambda: 1, correlation_id="call-A")
    queue.execute("b", lambda: 2, correlation_id="call-B")
    queue.execute("c", lambda: 3, correlation_id="call-A")
    a_entries = queue.journal_for("call-A")
    assert {e.operation for e in a_entries} == {"a", "c"}
    assert len(queue.journal_for("call-B")) == 1


def test_reconnect_hook_called_between_retries() -> None:
    reconnects = {"n": 0}

    def reconnect() -> None:
        reconnects["n"] += 1

    queue = _queue(max_retries=2, reconnect=reconnect)
    attempts = {"n": 0}

    def command() -> str:
        attempts["n"] += 1
        if attempts["n"] < 2:
            raise _RetryableError("x")
        return "ok"

    queue.execute("op", command)
    assert reconnects["n"] == 1


def test_backoff_is_bounded() -> None:
    queue = KiCadCommandQueue(base_delay_s=0.1, max_delay_s=0.5)
    assert queue.backoff_delay(1) == 0.1
    assert queue.backoff_delay(2) == 0.2
    assert queue.backoff_delay(3) == 0.4
    assert queue.backoff_delay(4) == 0.5  # capped
    assert queue.backoff_delay(10) == 0.5


def test_commands_are_serialized_under_concurrency() -> None:
    queue = KiCadCommandQueue()
    active = {"now": 0, "max": 0}
    guard = threading.Lock()

    def command() -> None:
        with guard:
            active["now"] += 1
            active["max"] = max(active["max"], active["now"])
        time.sleep(0.005)
        with guard:
            active["now"] -= 1

    threads = [
        threading.Thread(target=lambda i=i: queue.execute(f"op{i}", command)) for i in range(8)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert active["max"] == 1  # never two commands at once
    assert len(queue.journal) == 8


def test_singleton_accessor_resets() -> None:
    reset_command_queue()
    first = get_command_queue()
    assert get_command_queue() is first
    reset_command_queue()
    assert get_command_queue() is not first


def test_pcb_live_mutation_helper_routes_through_native_live_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import kicad_mcp.tools.pcb as pcb_mod

    calls: list[tuple[str, object]] = []

    def execute_live_board_mutation(
        operation: str,
        command: Callable[[object], str],
        *,
        verifier: object,
    ) -> str:
        calls.append((operation, verifier))
        return command(object())

    monkeypatch.setattr(pcb_mod, "execute_live_board_mutation", execute_live_board_mutation)

    result = pcb_mod._run_queued_ipc_mutation("pcb_save", lambda: "ok")

    assert result == "ok"
    assert calls == [("pcb_save", None)]


def test_mutation_timeout_after_possible_side_effect_is_never_replayed() -> None:
    reconnects = {"n": 0}
    calls = {"n": 0}

    def reconnect() -> None:
        reconnects["n"] += 1

    queue = _queue(max_retries=5, reconnect=reconnect)

    def command() -> str:
        calls["n"] += 1
        raise TimeoutError("response lost after mutation may have applied")

    from kicad_mcp.ipc.command_queue import AmbiguousMutationError

    with pytest.raises(AmbiguousMutationError, match="automatic retry is disabled"):
        queue.execute_mutation("pcb_add_track", command, correlation_id="mut-1")

    assert calls["n"] == 1
    assert reconnects["n"] == 0
    assert queue._slept == []  # type: ignore[attr-defined]
    entry = queue.journal[-1]
    assert entry.operation == "pcb_add_track"
    assert entry.correlation_id == "mut-1"
    assert entry.status == "ambiguous"
    assert entry.attempts == 1
    assert entry.error_class == "TimeoutError"


def test_mutation_retryable_disconnect_is_never_replayed() -> None:
    calls = {"n": 0}
    queue = _queue(max_retries=5)

    def command() -> str:
        calls["n"] += 1
        raise _RetryableError("connection lost")

    from kicad_mcp.ipc.command_queue import AmbiguousMutationError

    with pytest.raises(AmbiguousMutationError):
        queue.execute_mutation("pcb_add_via", command)

    assert calls["n"] == 1
    assert queue._slept == []  # type: ignore[attr-defined]
    assert queue.journal[-1].status == "ambiguous"
    assert queue.journal[-1].attempts == 1
    assert queue.journal[-1].error_code == "RETRY"


def test_mutation_non_retryable_error_preserves_original_failure() -> None:
    calls = {"n": 0}
    queue = _queue(max_retries=5)

    def command() -> str:
        calls["n"] += 1
        raise _FatalError("invalid request")

    with pytest.raises(_FatalError, match="invalid request"):
        queue.execute_mutation("pcb_add_track", command)

    assert calls["n"] == 1
    assert queue.journal[-1].status == "failed"
    assert queue.journal[-1].attempts == 1
    assert queue._slept == []  # type: ignore[attr-defined]


def test_mutation_success_executes_once_and_journals_success() -> None:
    calls = {"n": 0}
    queue = _queue(max_retries=5)

    def command() -> str:
        calls["n"] += 1
        return "created"

    assert queue.execute_mutation("pcb_add_track", command, correlation_id="mut-ok") == "created"
    assert calls["n"] == 1
    entry = queue.journal[-1]
    assert entry.status == "success"
    assert entry.attempts == 1
    assert entry.correlation_id == "mut-ok"
    assert queue._slept == []  # type: ignore[attr-defined]

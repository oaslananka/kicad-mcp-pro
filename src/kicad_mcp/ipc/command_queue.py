"""Centralized, serialized KiCad IPC command queue (issue #158).

KiCad's IPC API is event-driven and stateful: if independent tools each fire IPC
commands concurrently, GUI state, file state and operation ordering can drift. This
module provides a single serialization point with:

- a process-wide lock so commands run one at a time (single connection manager);
- bounded retry with exponential backoff for *retryable* failures only;
- modal/busy and timeout classification;
- idempotency keys so a retried tool call does not double-apply a mutation;
- an operation journal correlated with tool call IDs;
- an optional reconnect hook invoked before a retry.

The queue is transport-agnostic — callers pass a zero-argument ``command`` thunk —
so it is fully unit-testable without a running KiCad. It deliberately does **not**
enforce a hard wall-clock timeout (that belongs to the transport); instead it
*classifies* timeouts surfaced by the command so they can be retried.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, TypeVar

from .errors import KiCadIpcTimeoutError

T = TypeVar("T")

DEFAULT_MAX_RETRIES = 2
DEFAULT_BASE_DELAY_S = 0.05
DEFAULT_MAX_DELAY_S = 2.0
DEFAULT_JOURNAL_LIMIT = 1000


class RetryClass(StrEnum):
    """How a failure should be treated by the queue."""

    RETRYABLE = "retryable"
    NON_RETRYABLE = "non_retryable"
    TIMEOUT = "timeout"


class AmbiguousMutationError(RuntimeError):
    """A mutating IPC call may have applied before its transport response failed."""


def classify_error(exc: BaseException) -> RetryClass:
    """Classify an exception for retry handling.

    A ``TimeoutError`` (or the IPC timeout error) is TIMEOUT; any error exposing a
    truthy ``retryable`` attribute is RETRYABLE; everything else is conservatively
    NON_RETRYABLE so unknown failures are surfaced immediately rather than looped.
    """

    if isinstance(exc, (TimeoutError, KiCadIpcTimeoutError)):
        return RetryClass.TIMEOUT
    retryable = getattr(exc, "retryable", None)
    if retryable is True:
        return RetryClass.RETRYABLE
    return RetryClass.NON_RETRYABLE


@dataclass(frozen=True, slots=True)
class JournalEntry:
    """One queue execution, correlated with the originating tool call."""

    operation: str
    correlation_id: str
    idempotency_key: str | None
    attempts: int
    status: str  # "success" | "failed" | "deduplicated" | "ambiguous"
    duration_s: float
    error_code: str | None = None
    error_class: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "operation": self.operation,
            "correlation_id": self.correlation_id,
            "idempotency_key": self.idempotency_key,
            "attempts": self.attempts,
            "status": self.status,
            "duration_s": round(self.duration_s, 6),
            "error_code": self.error_code,
            "error_class": self.error_class,
        }


class KiCadCommandQueue:
    """Serialize and supervise KiCad IPC commands."""

    def __init__(
        self,
        *,
        max_retries: int = DEFAULT_MAX_RETRIES,
        base_delay_s: float = DEFAULT_BASE_DELAY_S,
        max_delay_s: float = DEFAULT_MAX_DELAY_S,
        reconnect: Callable[[], None] | None = None,
        sleep: Callable[[float], None] = time.sleep,
        time_fn: Callable[[], float] = time.monotonic,
        journal_limit: int = DEFAULT_JOURNAL_LIMIT,
    ) -> None:
        self._max_retries = max(0, max_retries)
        self._base_delay_s = base_delay_s
        self._max_delay_s = max_delay_s
        self._reconnect = reconnect
        self._sleep = sleep
        self._time = time_fn
        self._lock = threading.RLock()
        self._results: dict[str, Any] = {}
        self._journal: deque[JournalEntry] = deque(maxlen=journal_limit)

    def backoff_delay(self, attempt: int) -> float:
        """Return the deterministic backoff before ``attempt`` (1-based retry index)."""
        delay = self._base_delay_s * (2 ** max(0, attempt - 1))
        return float(min(self._max_delay_s, delay))

    def execute(
        self,
        operation: str,
        command: Callable[[], T],
        *,
        correlation_id: str = "",
        idempotency_key: str | None = None,
    ) -> T:
        """Run ``command`` under the serialization lock with retry + journaling.

        If ``idempotency_key`` was already executed successfully, the cached result
        is returned without re-running the command (the attempt is journaled as
        ``deduplicated``). Retryable failures are retried up to ``max_retries`` with
        exponential backoff, calling the reconnect hook (if any) between attempts.
        """

        with self._lock:
            if idempotency_key is not None and idempotency_key in self._results:
                self._journal.append(
                    JournalEntry(
                        operation=operation,
                        correlation_id=correlation_id,
                        idempotency_key=idempotency_key,
                        attempts=0,
                        status="deduplicated",
                        duration_s=0.0,
                    )
                )
                return self._results[idempotency_key]  # type: ignore[no-any-return]

            attempts = 0
            started = self._time()
            last_exc: BaseException | None = None
            while True:
                attempts += 1
                try:
                    result = command()
                except Exception as exc:  # noqa: BLE001 - classified below
                    last_exc = exc
                    classification = classify_error(exc)
                    can_retry = (
                        classification in (RetryClass.RETRYABLE, RetryClass.TIMEOUT)
                        and attempts <= self._max_retries
                    )
                    if can_retry:
                        try:
                            if self._reconnect is not None:
                                self._reconnect()
                        except Exception as reconnect_exc:  # noqa: BLE001 - journaled, then re-raised
                            self._journal.append(
                                JournalEntry(
                                    operation=operation,
                                    correlation_id=correlation_id,
                                    idempotency_key=idempotency_key,
                                    attempts=attempts,
                                    status="failed",
                                    duration_s=self._time() - started,
                                    error_code=getattr(reconnect_exc, "code", None),
                                    error_class=type(reconnect_exc).__name__,
                                )
                            )
                            raise
                        self._sleep(self.backoff_delay(attempts))
                        continue
                    self._journal.append(
                        JournalEntry(
                            operation=operation,
                            correlation_id=correlation_id,
                            idempotency_key=idempotency_key,
                            attempts=attempts,
                            status="failed",
                            duration_s=self._time() - started,
                            error_code=getattr(exc, "code", None),
                            error_class=type(exc).__name__,
                        )
                    )
                    raise
                else:
                    if idempotency_key is not None:
                        self._results[idempotency_key] = result
                    self._journal.append(
                        JournalEntry(
                            operation=operation,
                            correlation_id=correlation_id,
                            idempotency_key=idempotency_key,
                            attempts=attempts,
                            status="success",
                            duration_s=self._time() - started,
                        )
                    )
                    return result
            # Unreachable: the loop either returns or raises.
            raise last_exc  # pragma: no cover

    def execute_mutation[T](
        self,
        operation: str,
        command: Callable[[], T],
        *,
        correlation_id: str = "",
    ) -> T:
        """Execute one mutating IPC command exactly once under the queue lock.

        A timeout or retryable transport failure after the callable starts is
        ambiguous: KiCad may already have applied the mutation even though the
        response was lost.  Automatic replay is therefore disabled for this path.
        """
        with self._lock:
            started = self._time()
            try:
                result = command()
            except Exception as exc:  # noqa: BLE001 - classified and journaled below
                classification = classify_error(exc)
                ambiguous = classification in (RetryClass.RETRYABLE, RetryClass.TIMEOUT)
                self._journal.append(
                    JournalEntry(
                        operation=operation,
                        correlation_id=correlation_id,
                        idempotency_key=None,
                        attempts=1,
                        status="ambiguous" if ambiguous else "failed",
                        duration_s=self._time() - started,
                        error_code=getattr(exc, "code", None),
                        error_class=type(exc).__name__,
                    )
                )
                if ambiguous:
                    raise AmbiguousMutationError(
                        f"Mutation {operation!r} may have been applied before the IPC "
                        "failure; automatic retry is disabled."
                    ) from exc
                raise
            self._journal.append(
                JournalEntry(
                    operation=operation,
                    correlation_id=correlation_id,
                    idempotency_key=None,
                    attempts=1,
                    status="success",
                    duration_s=self._time() - started,
                )
            )
            return result

    @property
    def journal(self) -> tuple[JournalEntry, ...]:
        """Return the recorded journal entries (oldest first)."""
        with self._lock:
            return tuple(self._journal)

    def journal_for(self, correlation_id: str) -> tuple[JournalEntry, ...]:
        """Return journal entries for one tool call ID."""
        with self._lock:
            return tuple(e for e in self._journal if e.correlation_id == correlation_id)

    def clear_idempotency_cache(self) -> None:
        """Drop cached idempotent results (e.g. after a project switch)."""
        with self._lock:
            self._results.clear()


_QUEUE_LOCK = threading.Lock()
_QUEUE: KiCadCommandQueue | None = None


def get_command_queue() -> KiCadCommandQueue:
    """Return the process-wide IPC command queue, creating it on first use."""
    global _QUEUE
    if _QUEUE is None:
        with _QUEUE_LOCK:
            if _QUEUE is None:
                _QUEUE = KiCadCommandQueue()
    return _QUEUE


def reset_command_queue() -> None:
    """Reset the singleton (intended for tests)."""
    global _QUEUE
    with _QUEUE_LOCK:
        _QUEUE = None

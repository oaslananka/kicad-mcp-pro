"""Concurrency & Race Condition testing for KiCad MCP Pro components.

Verifies thread-safety, serialization locks, idempotency under concurrent execution,
and absence of deadlocks across multi-threaded operations.
"""

from __future__ import annotations

import concurrent.futures
import threading
import time
from pathlib import Path

import pytest

from kicad_mcp.ipc.command_queue import KiCadCommandQueue
from kicad_mcp.server import _record_tool_metric
from kicad_mcp.tools.schematic import parse_schematic_file
from kicad_mcp.web.state import get_metrics_snapshot, reset_metrics

FIXTURE_SCH = (
    Path(__file__).resolve().parents[2]
    / "packages"
    / "kicad-fixtures"
    / "fixtures"
    / "clean-led-kicad10"
    / "clean-led-kicad10.kicad_sch"
)


def test_concurrent_ipc_queue_deduplication() -> None:
    """Verify that multiple concurrent threads calling execute with the same
    idempotency_key run the underlying command exactly once without race conditions.
    """
    queue = KiCadCommandQueue()
    execution_counter = 0
    counter_lock = threading.Lock()

    def expensive_mutating_action() -> int:
        nonlocal execution_counter
        # Sleep briefly to enlarge race window if lock isn't serializing properly
        time.sleep(0.01)
        with counter_lock:
            execution_counter += 1
            return execution_counter

    num_threads = 20
    results: list[int] = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
        futures = [
            executor.submit(
                queue.execute,
                "concurrency_test_op",
                expensive_mutating_action,
                correlation_id=f"corr-{i}",
                idempotency_key="shared-idempotency-key-12345",
            )
            for i in range(num_threads)
        ]
        for f in concurrent.futures.as_completed(futures):
            results.append(f.result())

    # All 20 threads must receive the same result value (1)
    assert len(results) == num_threads
    assert all(r == 1 for r in results)
    # The actual mutation must have executed exactly once
    assert execution_counter == 1

    # Journal must contain 1 success entry and 19 deduplicated entries
    journal = queue.journal
    assert len(journal) == num_threads
    successes = [j for j in journal if j.status == "success"]
    dedupes = [j for j in journal if j.status == "deduplicated"]
    assert len(successes) == 1
    assert len(dedupes) == num_threads - 1


def test_concurrent_ipc_queue_independent_keys() -> None:
    """Verify that concurrent threads with independent keys all execute cleanly
    in serialization without deadlocks.
    """
    queue = KiCadCommandQueue()
    num_threads = 25
    counters = [0] * num_threads

    def worker_action(idx: int) -> int:
        counters[idx] += 1
        return idx * 2

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = [
            executor.submit(
                queue.execute,
                f"op_{i}",
                lambda i=i: worker_action(i),
                correlation_id=f"corr-{i}",
                idempotency_key=f"unique-key-{i}",
            )
            for i in range(num_threads)
        ]
        results = [f.result() for f in concurrent.futures.as_completed(futures)]

    assert len(results) == num_threads
    assert sum(counters) == num_threads
    assert set(results) == {i * 2 for i in range(num_threads)}


def test_concurrent_web_metrics_recording() -> None:
    """Verify thread-safety of metrics collection under simultaneous concurrent requests."""
    reset_metrics()
    num_threads = 30
    requests_per_thread = 20

    def record_batch(thread_id: int) -> None:
        for i in range(requests_per_thread):
            status = "ok" if (i % 4 != 0) else "error"
            _record_tool_metric(
                tool_name=f"tool_{(thread_id + i) % 5}",
                status=status,
                elapsed_ms=5.0 + (i % 10),
            )

    with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
        futures = [executor.submit(record_batch, t) for t in range(num_threads)]
        for f in concurrent.futures.as_completed(futures):
            f.result()

    metrics = get_metrics_snapshot()
    assert metrics["total_calls"] == num_threads * requests_per_thread


def test_concurrent_schematic_file_parsing() -> None:
    """Verify multiple concurrent readers can parse the same schematic file simultaneously
    without IO errors or corruption.
    """
    if not FIXTURE_SCH.exists():
        pytest.skip(f"Fixture schematic not found at {FIXTURE_SCH}")

    num_readers = 15

    def parse_worker() -> dict[str, object]:
        return parse_schematic_file(FIXTURE_SCH)

    with concurrent.futures.ThreadPoolExecutor(max_workers=num_readers) as executor:
        futures = [executor.submit(parse_worker) for _ in range(num_readers)]
        results = [f.result() for f in concurrent.futures.as_completed(futures)]

    assert len(results) == num_readers
    symbol_counts = [len(res.get("symbols", [])) for res in results]
    # Every reader must parse identical number of symbols
    assert len(set(symbol_counts)) == 1
    assert symbol_counts[0] > 0

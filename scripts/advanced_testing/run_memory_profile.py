"""Memory and leak profiling runner for KiCad MCP Pro.

Measures RAM consumption, peak memory, object allocation retention,
and detects memory leaks across repeated operations.
"""

from __future__ import annotations

import argparse
import gc
import json
import time
import tracemalloc
from pathlib import Path

from kicad_mcp.ipc.command_queue import KiCadCommandQueue
from kicad_mcp.tools.schematic import parse_schematic_file

FIXTURE_SCH = (
    Path(__file__).resolve().parents[2]
    / "packages"
    / "kicad-fixtures"
    / "fixtures"
    / "clean-led-kicad10"
    / "clean-led-kicad10.kicad_sch"
)


def profile_schematic_parsing(iterations: int = 50) -> dict[str, object]:
    """Repeatedly parse schematic and verify memory does not leak."""
    if not FIXTURE_SCH.exists():
        return {"error": "Fixture schematic not found"}

    gc.collect()
    tracemalloc.start()
    snapshot_before = tracemalloc.take_snapshot()

    for _ in range(iterations):
        data = parse_schematic_file(FIXTURE_SCH)
        if not data.get("symbols"):
            raise RuntimeError("Failed to parse symbols in benchmark")

    gc.collect()
    snapshot_after = tracemalloc.take_snapshot()
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    top_stats = snapshot_after.compare_to(snapshot_before, "lineno")
    total_retained_bytes = sum(stat.size_diff for stat in top_stats if stat.size_diff > 0)

    return {
        "workload": "schematic_parsing",
        "iterations": iterations,
        "peak_ram_mb": round(peak / (1024 * 1024), 3),
        "current_ram_mb": round(current / (1024 * 1024), 3),
        "retained_bytes": total_retained_bytes,
        "leak_detected": total_retained_bytes > 5 * 1024 * 1024,  # > 5MB retained is leak suspect
    }


def profile_ipc_queue(iterations: int = 500) -> dict[str, object]:
    """Repeatedly dispatch commands through queue and verify memory bounds."""
    queue = KiCadCommandQueue(journal_limit=iterations)

    gc.collect()
    tracemalloc.start()
    snapshot_before = tracemalloc.take_snapshot()

    for i in range(iterations):
        queue.execute("profile_op", lambda i=i: i * 2, correlation_id=f"corr-{i}")

    gc.collect()
    snapshot_after = tracemalloc.take_snapshot()
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    top_stats = snapshot_after.compare_to(snapshot_before, "lineno")
    total_retained = sum(stat.size_diff for stat in top_stats if stat.size_diff > 0)

    return {
        "workload": "ipc_queue_dispatch",
        "iterations": iterations,
        "peak_ram_mb": round(peak / (1024 * 1024), 3),
        "current_ram_mb": round(current / (1024 * 1024), 3),
        "retained_bytes": total_retained,
        "leak_detected": total_retained > 10 * 1024 * 1024,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Memory and Leak Profile Runner")
    parser.add_argument("--iterations", type=int, default=50)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    if args.output:
        # Fail closed: stale success must never survive a crashed producer.
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text('{"status": "INCOMPLETE"}\n', encoding="utf-8")

    print("Profiling schematic parsing...")
    sch_res = profile_schematic_parsing(iterations=args.iterations)
    print(f"Schematic: peak {sch_res.get('peak_ram_mb')} MB, leak={sch_res.get('leak_detected')}")

    print("Profiling IPC queue dispatch...")
    ipc_res = profile_ipc_queue(iterations=args.iterations * 10)
    print(f"IPC: peak {ipc_res.get('peak_ram_mb')} MB, leak={ipc_res.get('leak_detected')}")

    summary = {
        "timestamp": time.time(),
        "profiles": [sch_res, ipc_res],
        "all_clean": not (sch_res.get("leak_detected") or ipc_res.get("leak_detected")),
    }

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        print(f"Memory profile saved to {args.output}")
    else:
        print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()

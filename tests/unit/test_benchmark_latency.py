from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from kicad_mcp.server import build_server
from tests.conftest import call_tool_text


@pytest.mark.benchmark
@pytest.mark.anyio
async def test_tool_catalog_latency_against_baseline(sample_project: Path) -> None:
    _ = sample_project
    baseline = json.loads(
        Path("tests/fixtures/benchmark_latency_baseline.json").read_text(encoding="utf-8")
    )
    server = build_server("full")
    samples_ms: list[float] = []

    for _index in range(5):
        start = time.perf_counter()
        await call_tool_text(server, "kicad_list_tool_categories", {})
        samples_ms.append((time.perf_counter() - start) * 1000.0)

    p95_ms = sorted(samples_ms)[-1]
    allowed_ms = float(baseline["kicad_list_tool_categories_p95_ms"]) * 1.2
    output_path = os.environ.get("KICAD_MCP_BENCHMARK_JSON")
    if output_path:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "benchmark": "kicad_list_tool_categories",
                    "samples_ms": samples_ms,
                    "p95_ms": p95_ms,
                    "allowed_ms": allowed_ms,
                    "baseline_ms": float(baseline["kicad_list_tool_categories_p95_ms"]),
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    assert p95_ms <= allowed_ms, f"tool catalog p95 {p95_ms:.2f} ms > {allowed_ms:.2f} ms"

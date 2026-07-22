from __future__ import annotations

import json
import math
import os
import sys
import time
from pathlib import Path

import pytest

from kicad_mcp.ipc.capabilities import KiCadIpcCapabilityState
from kicad_mcp.ipc.discovery import KiCadIpcEndpoint
from kicad_mcp.server import build_server

PERFORMANCE_CATALOG_PATH = Path(__file__).resolve().parents[2] / "performance" / "baselines.json"
MEASUREMENT_OUTPUT_ENV = "KICAD_PERFORMANCE_MEASUREMENTS_JSON"
TOOLS_LIST_METRIC = "mcp.tools_list.response_ms"
# Discard the first calls: they pay one-time import / cache / JIT warm-up that is
# not representative of steady-state tools/list latency.
WARMUP_ITERATIONS = 3
# Enough samples for a meaningful nearest-rank p95 that tolerates a single spike.
MEASURE_ITERATIONS = 20


def _unavailable_ipc_state() -> KiCadIpcCapabilityState:
    """Return a deterministic unavailable IPC state for discovery tests."""
    return KiCadIpcCapabilityState(
        endpoint=KiCadIpcEndpoint(
            socket_path=None,
            source="default",
            token_configured=False,
            timeout_ms=10_000,
        ),
        reachable=False,
        version=None,
        api_version=None,
        major_version=None,
        live_pcb_context=False,
        live_schematic_context=False,
        headless_requested=False,
        operations={},
        diagnostics=(),
    )


def test_tools_list_reuses_runtime_capability_probe(
    monkeypatch: pytest.MonkeyPatch,
    sample_project: Path,
) -> None:
    """Avoid repeated cold KiCad IPC probes during one tools/list burst."""
    _ = sample_project
    calls = 0

    def fake_ipc_state() -> KiCadIpcCapabilityState:
        nonlocal calls
        calls += 1
        return _unavailable_ipc_state()

    monkeypatch.setattr("kicad_mcp.server.get_ipc_capability_state", fake_ipc_state)
    server = build_server("full")

    server.list_tools_sync()
    server.list_tools_sync()

    assert calls == 1


@pytest.mark.benchmark
@pytest.mark.anyio
async def test_tools_list_latency_against_shared_budget(
    monkeypatch: pytest.MonkeyPatch,
    sample_project: Path,
) -> None:
    _ = sample_project
    monkeypatch.setattr(
        "kicad_mcp.server.get_ipc_capability_state",
        _unavailable_ipc_state,
    )
    baseline = json.loads(PERFORMANCE_CATALOG_PATH.read_text(encoding="utf-8"))["metrics"][
        TOOLS_LIST_METRIC
    ]
    server = build_server("full")

    for _ in range(WARMUP_ITERATIONS):
        await server.list_tools()

    samples_ms: list[float] = []
    for _index in range(MEASURE_ITERATIONS):
        start = time.perf_counter()
        await server.list_tools()
        samples_ms.append((time.perf_counter() - start) * 1000.0)

    # Genuine nearest-rank p95 so a single scheduler/GC spike on a noisy hosted
    # runner does not fail the build (the previous max-of-5 was spike-sensitive).
    ordered = sorted(samples_ms)
    p95_ms = ordered[max(0, math.ceil(0.95 * len(ordered)) - 1)]
    # Hosted macOS and Windows Actions runners run markedly slower, with higher
    # variance, than the Linux runners the baseline was measured on.
    multiplier = 1.2 if sys.platform == "linux" else 2.5
    allowed_ms = float(baseline["baseline"]) * multiplier
    output_path = os.environ.get(MEASUREMENT_OUTPUT_ENV)
    if output_path:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "schemaVersion": 1,
                    "source": "tests/unit/test_benchmark_latency.py",
                    "measurements": [
                        {
                            "metric": TOOLS_LIST_METRIC,
                            "value": p95_ms,
                            "unit": baseline["unit"],
                            "statistic": "p95",
                            "samples": len(samples_ms),
                            "sampleValues": samples_ms,
                        }
                    ],
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    assert p95_ms <= allowed_ms, f"tools/list p95 {p95_ms:.2f} ms > {allowed_ms:.2f} ms"

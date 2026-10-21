"""Load, stress, and latency distribution runner for KiCad MCP Pro web/API endpoints.

Simulates concurrent virtual users (VUs) and measures latency distribution
(p50, p95, p99, max), throughput (RPS), and error rates.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import statistics
import time
from pathlib import Path
from typing import cast

from starlette.applications import Starlette
from starlette.testclient import TestClient

from kicad_mcp.web.routes import web_routes

# The local GitHub runner has no KiCad IPC server. Keep its fast, hermetic
# API endpoints separate from diagnostics that probe live KiCad capabilities.
_PROFILES = {
    "lightweight": ("/api/info", "/api/metrics"),
    "runtime": ("/api/status", "/api/health", "/api/info", "/api/metrics"),
}


def _request_result(client: TestClient, url: str) -> tuple[float, bool]:
    """Measure transport plus KiCad readiness instead of just HTTP status."""
    req_start = time.perf_counter()
    try:
        resp = client.get(url)
        elapsed_ms = (time.perf_counter() - req_start) * 1000.0
        if resp.status_code != 200:
            return elapsed_ms, False
        if url == "/api/health":
            return elapsed_ms, resp.json().get("ok") is True
        if url == "/api/status":
            return elapsed_ms, resp.json().get("health", {}).get("ok") is True
        return elapsed_ms, True
    except Exception:
        elapsed_ms = (time.perf_counter() - req_start) * 1000.0
        return elapsed_ms, False


def run_load_benchmark(
    vus: int = 10, total_requests: int = 200, *, profile: str = "runtime"
) -> dict[str, object]:
    """Execute load test using Starlette TestClient across worker threads."""
    if vus < 1 or total_requests < 1:
        raise ValueError("vus and total_requests must be positive")
    endpoints = _PROFILES[profile]
    app = Starlette(routes=web_routes)
    client = TestClient(app, raise_server_exceptions=False)

    latencies: list[float] = []
    errors: int = 0

    start_wall_time = time.time()

    def worker_task(req_id: int) -> tuple[float, bool]:
        return _request_result(client, endpoints[req_id % len(endpoints)])

    with concurrent.futures.ThreadPoolExecutor(max_workers=vus) as executor:
        futures = [executor.submit(worker_task, i) for i in range(total_requests)]
        for f in concurrent.futures.as_completed(futures):
            dur, ok = f.result()
            latencies.append(dur)
            if not ok:
                errors += 1

    total_duration_s = time.time() - start_wall_time
    rps = round(total_requests / total_duration_s, 2) if total_duration_s > 0 else 0

    sorted_latencies = sorted(latencies)
    p50 = statistics.median(sorted_latencies) if sorted_latencies else 0.0
    p95_idx = int(len(sorted_latencies) * 0.95)
    p99_idx = int(len(sorted_latencies) * 0.99)
    p95 = sorted_latencies[min(p95_idx, len(sorted_latencies) - 1)] if sorted_latencies else 0.0
    p99 = sorted_latencies[min(p99_idx, len(sorted_latencies) - 1)] if sorted_latencies else 0.0

    error_rate_pct = round((errors / total_requests) * 100, 2)

    return {
        "profile": profile,
        "endpoints": list(endpoints),
        "virtual_users": vus,
        "total_requests": total_requests,
        "successful_requests": total_requests - errors,
        "failed_requests": errors,
        "error_rate_percent": error_rate_pct,
        "throughput_rps": rps,
        "total_duration_s": round(total_duration_s, 3),
        "latencies_ms": {
            "min": round(sorted_latencies[0], 2) if sorted_latencies else 0.0,
            "mean": round(statistics.mean(sorted_latencies), 2) if sorted_latencies else 0.0,
            "p50": round(p50, 2),
            "p95": round(p95, 2),
            "p99": round(p99, 2),
            "max": round(sorted_latencies[-1], 2) if sorted_latencies else 0.0,
        },
        "pass_criteria_met": error_rate_pct < 1.0 and p95 < 200.0,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="KiCad MCP Pro Load & Stress Runner")
    parser.add_argument("--vus", type=int, default=10, help="Number of concurrent virtual users")
    parser.add_argument("--requests", type=int, default=200, help="Total requests to dispatch")
    parser.add_argument("--output", type=Path, default=None, help="Output JSON path")
    parser.add_argument("--profile", choices=tuple(_PROFILES), default="runtime")
    parser.add_argument(
        "--enforce", action="store_true", help="Exit nonzero when the measured SLA fails"
    )
    args = parser.parse_args()

    if args.output:
        # Fail closed: do not re-use a previous successful benchmark if this run crashes.
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text('{"status": "INCOMPLETE"}\n', encoding="utf-8")
    if args.vus < 1 or args.requests < 1:
        parser.error("--vus and --requests must be positive")
    print(f"Starting {args.profile} load test: {args.vus} VUs, {args.requests} requests...")
    results = run_load_benchmark(vus=args.vus, total_requests=args.requests, profile=args.profile)
    print(
        f"Throughput: {results['throughput_rps']} RPS | "
        f"Error Rate: {results['error_rate_percent']}%"
    )
    lat = cast("dict[str, float]", results["latencies_ms"])
    print(
        f"Latencies (ms): p50={lat['p50']} | p95={lat['p95']} | p99={lat['p99']} | max={lat['max']}"
    )
    print(f"Pass criteria met: {results['pass_criteria_met']}")

    summary = {
        "timestamp": time.time(),
        "benchmark": results,
    }

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        print(f"Load benchmark saved to {args.output}")
    else:
        print(json.dumps(summary, indent=2))

    if args.enforce and not results["pass_criteria_met"]:
        raise SystemExit("Load benchmark failed required latency/error criteria")


if __name__ == "__main__":
    main()

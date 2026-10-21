"""Behavior contracts for CI load benchmarks and their evidence accounting."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

from scripts.advanced_testing import report_collector, run_load_test, run_memory_profile


def _evidence(base: Path, name: str, data: object) -> None:
    target = base / "current" / f"{name}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(data), encoding="utf-8")


def _benchmark(profile: str, passed: bool) -> dict[str, object]:
    return {
        "benchmark": {
            "profile": profile,
            "pass_criteria_met": passed,
            "total_requests": 100,
            "error_rate_percent": 0.0 if passed else 2.0,
            "latencies_ms": {"p95": 60.0 if passed else 500.0},
        }
    }


def _memory(clean: bool = True) -> dict[str, object]:
    return {
        "all_clean": clean,
        "profiles": [
            {"workload": "schematic_parsing", "leak_detected": not clean},
            {"workload": "ipc_queue_dispatch", "leak_detected": False},
        ],
    }


@pytest.fixture
def fixed_commit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        report_collector,
        "get_git_info",
        lambda: {"commit_sha": "a" * 40, "short_sha": "aaaaaaa", "branch": "test", "dirty": False},
    )


def test_lightweight_and_runtime_profiles_check_real_health(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    visited: list[str] = []

    class Response:
        status_code = 200

        def __init__(self, url: str) -> None:
            self.url = url

        def json(self) -> dict[str, Any]:
            return {"ok": False, "health": {"ok": False}}

    class Client:
        def __init__(self, _app: object, **_kwargs: object) -> None:
            pass

        def get(self, url: str) -> Response:
            visited.append(url)
            return Response(url)

    monkeypatch.setattr(run_load_test, "TestClient", Client)
    lightweight = run_load_test.run_load_benchmark(vus=2, total_requests=4, profile="lightweight")
    assert lightweight["pass_criteria_met"] is True
    assert lightweight["failed_requests"] == 0
    assert visited == ["/api/info", "/api/metrics", "/api/info", "/api/metrics"] or sorted(
        visited
    ) == sorted(["/api/info", "/api/metrics"] * 2)

    visited.clear()
    runtime = run_load_test.run_load_benchmark(vus=2, total_requests=4, profile="runtime")
    assert runtime["failed_requests"] == 2
    assert runtime["error_rate_percent"] == 50
    assert runtime["pass_criteria_met"] is False


@pytest.mark.parametrize("vus,requests", [(0, 1), (1, 0), (-1, 2)])
def test_load_benchmark_rejects_invalid_workload(vus: int, requests: int) -> None:
    with pytest.raises(ValueError, match="must be positive"):
        run_load_test.run_load_benchmark(vus=vus, total_requests=requests)


def test_enforced_load_failure_still_writes_evidence(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    output = tmp_path / "failure.json"
    monkeypatch.setattr(
        run_load_test,
        "run_load_benchmark",
        lambda **_args: {
            **_benchmark("lightweight", False)["benchmark"],
            "throughput_rps": 1,
            "latencies_ms": {"p50": 5, "p95": 500, "p99": 600, "max": 600},
        },
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["run_load_test.py", "--profile", "lightweight", "--enforce", "--output", str(output)],
    )
    with pytest.raises(SystemExit, match="failed required latency"):
        run_load_test.main()
    assert json.loads(output.read_text(encoding="utf-8"))["benchmark"]["pass_criteria_met"] is False


def test_evidence_reports_diagnostic_failure_as_warning(fixed_commit: None, tmp_path: Path) -> None:
    _evidence(tmp_path, "memory-profile", _memory())
    _evidence(tmp_path, "performance-benchmarks", _benchmark("lightweight", True))
    _evidence(tmp_path, "runtime-benchmarks", _benchmark("runtime", False))
    result_dir = report_collector.collect_evidence(tmp_path)
    summary = json.loads((result_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["status"] == "WARN"
    assert summary["layers"]["KiCad Runtime Benchmark (diagnostic)"] == "WARN"
    assert (result_dir / "runtime-benchmarks.json").is_file()
    report = (result_dir / "report.md").read_text(encoding="utf-8")
    assert "**WARN**" in report
    assert "KiCad Runtime Benchmark (diagnostic) | WARN" in report
    assert "Property & Invariants (Hypothesis) | PASS" not in report


@pytest.mark.parametrize(
    ("broken_name", "content"),
    [
        ("performance-benchmarks", _benchmark("lightweight", False)),
        ("performance-benchmarks", _benchmark("runtime", True)),
        ("memory-profile", {"all_clean": True, "profiles": [{"error": "missing fixture"}]}),
    ],
)
def test_required_evidence_failure_is_not_reported_as_pass(
    fixed_commit: None, tmp_path: Path, broken_name: str, content: object
) -> None:
    _evidence(tmp_path, "memory-profile", _memory())
    _evidence(tmp_path, "performance-benchmarks", _benchmark("lightweight", True))
    _evidence(tmp_path, broken_name, content)
    result_dir = report_collector.collect_evidence(tmp_path)
    summary = json.loads((result_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["status"] == "FAIL"


def test_missing_and_invalid_evidence_cannot_pass(fixed_commit: None, tmp_path: Path) -> None:
    current = tmp_path / "current"
    current.mkdir()
    (current / "performance-benchmarks.json").write_text("{broken", encoding="utf-8")
    result_dir = report_collector.collect_evidence(tmp_path)
    summary = json.loads((result_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["status"] == "FAIL"
    assert (result_dir / "summary.json").is_file()
    assert not (result_dir / "performance-benchmarks.json").exists()


def test_complete_evidence_passes(fixed_commit: None, tmp_path: Path) -> None:
    _evidence(tmp_path, "memory-profile", _memory())
    _evidence(tmp_path, "performance-benchmarks", _benchmark("lightweight", True))
    _evidence(tmp_path, "runtime-benchmarks", _benchmark("runtime", True))
    target = report_collector.collect_evidence(tmp_path)
    assert json.loads((target / "summary.json").read_text(encoding="utf-8"))["status"] == "PASS"


def test_collector_cli_exits_nonzero_when_required_evidence_missing(
    fixed_commit: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys, "argv", ["report_collector.py", "--output-base", str(tmp_path)])
    with pytest.raises(SystemExit, match="Required Advanced QA evidence failed"):
        report_collector.main()
    assert (tmp_path / "aaaaaaa" / "summary.json").is_file()


def test_workflow_preserves_qa_evidence_and_summary_after_failed_gate() -> None:
    workflow = Path(__file__).resolve().parents[2] / ".github/workflows/advanced-testing.yml"
    steps = yaml.safe_load(workflow.read_text(encoding="utf-8"))["jobs"]["advanced-qa"]["steps"]
    named_steps = {step["name"]: step for step in steps if "name" in step}
    expected_condition = "${{ !cancelled() }}"
    for name in (
        "Run KiCad Runtime Benchmark (diagnostic)",
        "Collect QA Evidence & Generate Report",
        "Publish Advanced QA Evidence Summary",
    ):
        assert named_steps[name]["if"] == expected_condition
    publisher = named_steps["Publish Advanced QA Evidence Summary"]["run"]
    assert 'if [ -f "$report" ]; then' in publisher
    assert "Advanced QA report was not generated." in publisher
    assert named_steps["Upload Advanced QA Evidence Artifacts"]["if"] == "always()"
    assert "--enforce" in named_steps["Run Lightweight API Load Benchmark (required)"]["run"]
    assert named_steps["Run KiCad Runtime Benchmark (diagnostic)"]["continue-on-error"] is True
    assert "continue-on-error" not in named_steps["Run Lightweight API Load Benchmark (required)"]


def test_failed_load_producer_clears_stale_evidence(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    output = tmp_path / "previous-benchmark.json"
    output.write_text('{"benchmark":{"pass_criteria_met":true}}', encoding="utf-8")
    monkeypatch.setattr(
        run_load_test,
        "run_load_benchmark",
        lambda **_args: (_ for _ in ()).throw(RuntimeError("producer failed")),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["run_load_test.py", "--output", str(output)],
    )
    with pytest.raises(RuntimeError, match="producer failed"):
        run_load_test.main()
    assert json.loads(output.read_text(encoding="utf-8")) == {"status": "INCOMPLETE"}


def test_failed_memory_producer_clears_stale_evidence(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    output = tmp_path / "previous-memory-profile.json"
    output.write_text('{"all_clean":true}', encoding="utf-8")
    monkeypatch.setattr(
        run_memory_profile,
        "profile_schematic_parsing",
        lambda **_args: (_ for _ in ()).throw(RuntimeError("producer failed")),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["run_memory_profile.py", "--output", str(output)],
    )
    with pytest.raises(RuntimeError, match="producer failed"):
        run_memory_profile.main()
    assert json.loads(output.read_text(encoding="utf-8")) == {"status": "INCOMPLETE"}


@pytest.mark.parametrize(
    ("url", "status_code", "payload", "expected"),
    [
        ("/api/info", 200, {}, True),
        ("/api/info", 503, {}, False),
        ("/api/health", 200, {"ok": True}, True),
        ("/api/status", 200, {"health": {"ok": True}}, True),
    ],
)
def test_request_result_distinguishes_transport_and_readiness(
    url: str, status_code: int, payload: object, expected: bool
) -> None:
    class Response:
        def __init__(self) -> None:
            self.status_code = status_code

        def json(self) -> object:
            return payload

    class Client:
        def get(self, _url: str) -> Response:
            return Response()

    latency, succeeded = run_load_test._request_result(Client(), url)  # type: ignore[arg-type]
    assert latency >= 0.0
    assert succeeded is expected


def test_request_result_converts_transport_exception_to_failure() -> None:
    class OfflineClient:
        def get(self, _url: str) -> None:
            raise ConnectionError("KiCad connection unavailable")

    latency, succeeded = run_load_test._request_result(  # type: ignore[arg-type]
        OfflineClient(), "/api/health"
    )
    assert latency >= 0.0
    assert succeeded is False


def test_evidence_benchmark_rejects_missing_benchmark_object() -> None:
    assert report_collector._benchmark_ok({"benchmark": False}, "lightweight") is False


def test_load_cli_rejects_invalid_workload(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["run_load_test.py", "--vus", "0"])
    with pytest.raises(SystemExit) as invalid:
        run_load_test.main()
    assert invalid.value.code == 2

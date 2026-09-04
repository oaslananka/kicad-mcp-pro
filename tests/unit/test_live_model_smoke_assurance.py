"""Degraded-pass policy tests for bounded live-model smoke evidence."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import kicad_mcp.evals.smoke_assurance as smoke_assurance
from kicad_mcp.errors import UnsafePathError
from kicad_mcp.evals.smoke_assurance import evaluate_smoke_assurance

CONFIGS = ("alpha", "beta", "gamma")
REVISION = "a" * 40


def _evidence(
    config_id: str,
    *,
    adapter_failures: int = 0,
    selection_failures: int = 0,
    safety_violations: int = 0,
    forbidden_violations: int = 0,
    call_limit_violations: int = 0,
    unnecessary_calls: int = 0,
    complete: bool = True,
) -> dict[str, object]:
    completed = 11 - adapter_failures
    quality_failure = selection_failures > 0 or unnecessary_calls > 0
    safety_failure = safety_violations > 0 or forbidden_violations > 0 or call_limit_violations > 0
    return {
        "schema_version": 1,
        "complete": complete,
        "configuration": {
            "id": config_id,
            "host": "test-host",
            "model": f"model-{config_id}",
            "adapter": "subprocess",
        },
        "source_revision": REVISION,
        "repeats": 1,
        "limits": {},
        "usage": {
            "total_tool_calls": completed,
            "total_tokens": completed * 100,
            "total_cost_micros": 0,
            "token_observations": completed,
            "cost_observations": 0,
        },
        "summary": {
            "cases": completed,
            "runs": 1,
            "observations": completed,
            "planned_observations": 11,
            "completed_observations": completed,
            "passed": completed - selection_failures,
            "pass_rate": 1.0 if completed else 0.0,
            "mean_recall": 1.0 if completed else 0.0,
            "behavior_match_rate": 1.0 if completed else 0.0,
            "violations": safety_violations + forbidden_violations,
            "safety_violations": safety_violations,
            "forbidden_violations": forbidden_violations,
            "unnecessary_calls": unnecessary_calls,
            "unnecessary_call_rate": 0.0,
            "mean_calls": 1.0 if completed else 0.0,
            "call_limit_violations": call_limit_violations,
            "p95_latency_ms": 100.0 if completed else None,
            "mean_tokens": 100.0 if completed else None,
            "token_coverage": 1.0 if completed else 0.0,
            "cost_coverage": 0.0,
            "nondeterministic_cases": [],
            "instability_rate": 0.0,
            "adapter_failures": adapter_failures,
            "selection_failures": selection_failures,
            "pipeline_passed": not (adapter_failures or quality_failure or safety_failure),
        },
        "thresholds": {
            "passed": not quality_failure and not safety_failure and adapter_failures == 0,
            "failures": [],
        },
        "executions": [],
    }


def _write(root: Path, values: list[dict[str, object]]) -> list[Path]:
    paths: list[Path] = []
    for value in values:
        config_id = value["configuration"]["id"]  # type: ignore[index]
        path = root / str(config_id) / "evidence.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(value), encoding="utf-8")
        paths.append(path)
    return paths


def test_smoke_assurance_passes_three_clean_configurations(tmp_path: Path) -> None:
    report = evaluate_smoke_assurance(
        _write(tmp_path, [_evidence(config_id) for config_id in CONFIGS]),
        required_configurations=CONFIGS,
        minimum_successful_configurations=2,
        expected_source_revision=REVISION,
    )

    assert report["passed"] is True
    assert report["degraded"] is False
    assert report["successful_configurations"] == list(CONFIGS)
    assert all(not values for values in report["classifications"].values())


def test_smoke_assurance_degraded_passes_two_clean_and_one_infrastructure_failure(
    tmp_path: Path,
) -> None:
    report = evaluate_smoke_assurance(
        _write(
            tmp_path,
            [
                _evidence("alpha"),
                _evidence("beta"),
                _evidence("gamma", adapter_failures=11, complete=False),
            ],
        ),
        required_configurations=CONFIGS,
        minimum_successful_configurations=2,
        expected_source_revision=REVISION,
    )

    assert report["passed"] is True
    assert report["degraded"] is True
    assert report["successful_configurations"] == ["alpha", "beta"]
    assert report["classifications"]["infrastructure_failures"] == [
        "gamma: adapter_failures=11",
        "gamma: checkpoint incomplete",
        "gamma: completed_observations=0 planned=11",
    ]
    assert report["classifications"]["quality_failures"] == []
    assert report["classifications"]["safety_failures"] == []


def test_smoke_assurance_blocks_when_fewer_than_minimum_configurations_pass(
    tmp_path: Path,
) -> None:
    report = evaluate_smoke_assurance(
        _write(
            tmp_path,
            [
                _evidence("alpha"),
                _evidence("beta", adapter_failures=11, complete=False),
                _evidence("gamma", adapter_failures=11, complete=False),
            ],
        ),
        required_configurations=CONFIGS,
        minimum_successful_configurations=2,
        expected_source_revision=REVISION,
    )

    assert report["passed"] is False
    assert report["successful_configurations"] == ["alpha"]
    assert report["classifications"]["quality_failures"] == [
        "successful configurations 1 below required 2"
    ]


def test_smoke_assurance_blocks_safety_or_quality_failures(tmp_path: Path) -> None:
    report = evaluate_smoke_assurance(
        _write(
            tmp_path,
            [
                _evidence("alpha"),
                _evidence("beta", safety_violations=1),
                _evidence("gamma", selection_failures=1),
            ],
        ),
        required_configurations=CONFIGS,
        minimum_successful_configurations=2,
        expected_source_revision=REVISION,
    )

    assert report["passed"] is False
    assert report["classifications"]["safety_failures"] == [
        "beta: safety=1 forbidden=0 call_limit=0"
    ]
    assert report["classifications"]["quality_failures"] == [
        "gamma: selection failures present",
        "successful configurations 1 below required 2",
    ]


def test_smoke_assurance_blocks_invalid_or_mismatched_evidence(tmp_path: Path) -> None:
    values = [_evidence(config_id) for config_id in CONFIGS]
    values[2]["source_revision"] = "b" * 40
    paths = _write(tmp_path, values)
    invalid = tmp_path / "invalid" / "evidence.json"
    invalid.parent.mkdir()
    invalid.write_text("not-json", encoding="utf-8")

    report = evaluate_smoke_assurance(
        [*paths, invalid],
        required_configurations=CONFIGS,
        minimum_successful_configurations=2,
        expected_source_revision=REVISION,
    )

    assert report["passed"] is False
    assert len(report["classifications"]["integrity_failures"]) == 2
    assert "prompt" not in json.dumps(report)


def _write_status(
    root: Path,
    config_id: str,
    *,
    state: str,
    runner_exit_code: int | None,
    source_revision: str = REVISION,
) -> Path:
    path = root / config_id / "status.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "configuration_id": config_id,
                "source_revision": source_revision,
                "state": state,
                "runner_exit_code": runner_exit_code,
            }
        ),
        encoding="utf-8",
    )
    return path


def test_smoke_assurance_blocks_runner_configuration_or_evidence_failure(
    tmp_path: Path,
) -> None:
    evidence = _write(tmp_path, [_evidence("alpha"), _evidence("beta")])
    statuses = [
        _write_status(tmp_path, "alpha", state="completed", runner_exit_code=0),
        _write_status(tmp_path, "beta", state="completed", runner_exit_code=0),
        _write_status(tmp_path, "gamma", state="completed", runner_exit_code=2),
    ]

    report = evaluate_smoke_assurance(
        evidence,
        status_paths=statuses,
        required_configurations=CONFIGS,
        minimum_successful_configurations=2,
        expected_source_revision=REVISION,
    )

    assert report["passed"] is False
    assert report["successful_configurations"] == ["alpha", "beta"]
    assert report["classifications"]["integrity_failures"] == [
        "gamma: runner configuration or evidence failure"
    ]


def test_smoke_assurance_does_not_count_running_status_as_clean(tmp_path: Path) -> None:
    evidence = _write(tmp_path, [_evidence(config_id) for config_id in CONFIGS])
    statuses = [
        _write_status(tmp_path, "alpha", state="completed", runner_exit_code=0),
        _write_status(tmp_path, "beta", state="completed", runner_exit_code=0),
        _write_status(tmp_path, "gamma", state="running", runner_exit_code=None),
    ]

    report = evaluate_smoke_assurance(
        evidence,
        status_paths=statuses,
        required_configurations=CONFIGS,
        minimum_successful_configurations=2,
        expected_source_revision=REVISION,
    )

    assert report["passed"] is True
    assert report["degraded"] is True
    assert report["successful_configurations"] == ["alpha", "beta"]
    assert report["classifications"]["infrastructure_failures"] == ["gamma: run incomplete"]


def test_smoke_assurance_blocks_unexplained_pipeline_threshold_failure(tmp_path: Path) -> None:
    values = [_evidence(config_id) for config_id in CONFIGS]
    gamma_summary = values[2]["summary"]
    assert isinstance(gamma_summary, dict)
    gamma_summary["pipeline_passed"] = False
    values[2]["thresholds"] = {
        "passed": False,
        "failures": ["pass_rate below minimum"],
    }

    report = evaluate_smoke_assurance(
        _write(tmp_path, values),
        required_configurations=CONFIGS,
        minimum_successful_configurations=2,
        expected_source_revision=REVISION,
    )

    assert report["passed"] is False
    assert report["classifications"]["quality_failures"] == ["gamma: pipeline thresholds failed"]


def test_smoke_assurance_blocks_missing_required_status(tmp_path: Path) -> None:
    evidence = _write(tmp_path, [_evidence(config_id) for config_id in CONFIGS])
    statuses = [
        _write_status(tmp_path, "alpha", state="completed", runner_exit_code=0),
        _write_status(tmp_path, "beta", state="completed", runner_exit_code=0),
    ]

    report = evaluate_smoke_assurance(
        evidence,
        status_paths=statuses,
        require_status=True,
        required_configurations=CONFIGS,
        minimum_successful_configurations=2,
        expected_source_revision=REVISION,
    )

    assert report["passed"] is False
    assert report["classifications"]["integrity_failures"] == ["gamma: status missing"]
    assert report["classifications"]["infrastructure_failures"] == []


def test_smoke_assurance_writer_rejects_non_allowlisted_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(Path, "write_text", lambda *_args, **_kwargs: 0)

    with pytest.raises(UnsafePathError, match="fixed repository artifact path"):
        smoke_assurance.write_smoke_assurance_report("ignored.json", {"passed": True})


def test_smoke_assurance_writer_uses_fixed_repository_artifact_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(smoke_assurance, "_REPO_ROOT", tmp_path)

    output = smoke_assurance.write_smoke_assurance_report(
        "artifacts/live-model-smoke-assurance/report.json", {"passed": True}
    )

    assert output == (tmp_path / "artifacts/live-model-smoke-assurance/report.json").resolve()
    assert json.loads(output.read_text(encoding="utf-8")) == {"passed": True}

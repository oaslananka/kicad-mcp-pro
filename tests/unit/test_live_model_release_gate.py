"""Aggregate live-model release-gate contract tests."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from kicad_mcp.evals.live_config import load_configurations
from kicad_mcp.evals.release_gate import evaluate_release_gate, write_release_gate_report
from kicad_mcp.evals.tool_selection import load_cases

ROOT = Path(__file__).resolve().parents[2]
CONFIGURATIONS = ROOT / "evals/live/configurations.yaml"
CASES = ROOT / "evals/tool_selection/cases.yaml"
THRESHOLDS = ROOT / "evals/tool_selection/thresholds.yaml"

CONFIG_IDS = (
    "nvidia-nemotron-3-nano-30b-a3b",
    "nvidia-mistral-medium-3-5-128b",
    "opencode-cli-nemotron-3-ultra-free",
)
MODELS = (
    "nvidia/nemotron-3-nano-30b-a3b",
    "mistralai/mistral-medium-3.5-128b",
    "nemotron-3-ultra-free",
)
HOSTS = ("nvidia-nim", "nvidia-nim", "opencode-zen-cli")
REQUEST_INTERVALS = (5.0, 5.0, 0.0)
REQUIRED_ENVS = (
    ("NVIDIA_API_KEY",),
    ("NVIDIA_API_KEY",),
    ("OPENCODE_ZEN_API_KEY",),
)
COMMANDS = (
    (
        "python",
        "scripts/nvidia_nim_eval_adapter.py",
        "--model",
        MODELS[0],
        "--structured-output",
        "none",
    ),
    (
        "python",
        "scripts/nvidia_nim_eval_adapter.py",
        "--model",
        MODELS[1],
        "--timeout-seconds",
        "65",
        "--structured-output",
        "none",
    ),
    (
        "python",
        "scripts/opencode_cli_eval_adapter.py",
        "--model",
        MODELS[2],
        "--opencode-bin",
        "opencode",
        "--timeout-seconds",
        "65",
    ),
)
CONFIG_HOSTS = dict(zip(CONFIG_IDS, HOSTS, strict=True))


def _evidence(
    config_id: str,
    model: str,
    *,
    pass_rate: float = 0.98,
    mean_recall: float = 0.99,
    safety_violations: int = 0,
    forbidden_violations: int = 0,
    unnecessary_call_rate: float = 0.01,
    instability_rate: float = 0.01,
    p95_latency_ms: float | None = 900,
    mean_tokens: float | None = 180,
    token_coverage: float = 1.0,
    adapter_failures: int = 0,
    selection_failures: int = 0,
    executions: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "complete": True,
        "configuration": {
            "id": config_id,
            "host": CONFIG_HOSTS.get(config_id, "nvidia-nim"),
            "model": model,
            "adapter": "subprocess",
        },
        "source_revision": "a" * 40,
        "repeats": 3,
        "limits": {},
        "usage": {
            "total_tool_calls": 120,
            "total_tokens": 35100,
            "total_cost_micros": 0,
            "token_observations": 195 if token_coverage == 1.0 else 0,
            "cost_observations": 0,
        },
        "summary": {
            "cases": 65,
            "runs": 3,
            "observations": 195,
            "planned_observations": 195,
            "completed_observations": 195 - adapter_failures,
            "passed": round(195 * pass_rate),
            "pass_rate": pass_rate,
            "mean_recall": mean_recall,
            "behavior_match_rate": 1.0,
            "violations": safety_violations + forbidden_violations,
            "safety_violations": safety_violations,
            "forbidden_violations": forbidden_violations,
            "unnecessary_calls": 1,
            "unnecessary_call_rate": unnecessary_call_rate,
            "mean_calls": 1.0,
            "call_limit_violations": 0,
            "p95_latency_ms": p95_latency_ms,
            "mean_tokens": mean_tokens,
            "token_coverage": token_coverage,
            "cost_coverage": 0.0,
            "nondeterministic_cases": [],
            "instability_rate": instability_rate,
            "adapter_failures": adapter_failures,
            "selection_failures": selection_failures,
            "pipeline_passed": not (
                safety_violations or forbidden_violations or adapter_failures or selection_failures
            ),
        },
        "thresholds": {"passed": True, "failures": []},
        "executions": executions or [],
    }


def _write_evidence(root: Path, values: list[dict[str, object]]) -> list[Path]:
    paths: list[Path] = []
    for value in values:
        config_id = value["configuration"]["id"]  # type: ignore[index]
        path = root / str(config_id) / "evidence.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(value), encoding="utf-8")
        paths.append(path)
    return paths


def _baseline(path: Path, *, approved: bool = True) -> Path:
    payload = {
        "schema_version": 1,
        "approved": approved,
        "minimum_repeats": 3,
        "required_configurations": list(CONFIG_IDS),
        "configurations": {
            config_id: {
                "host": host,
                "model": model,
                "token_metrics_required": True,
                "metrics": {
                    "pass_rate": 0.98,
                    "mean_recall": 0.99,
                    "unnecessary_call_rate": 0.01,
                    "instability_rate": 0.01,
                    "p95_latency_ms": 900,
                    "mean_tokens": 180,
                },
            }
            for config_id, model, host in zip(CONFIG_IDS, MODELS, HOSTS, strict=True)
        },
    }
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return path


def test_gate_passes_three_approved_repeated_configurations(tmp_path: Path) -> None:
    evidence = _write_evidence(
        tmp_path / "evidence",
        [_evidence(config_id, model) for config_id, model in zip(CONFIG_IDS, MODELS, strict=True)],
    )

    report = evaluate_release_gate(
        evidence,
        baseline_path=_baseline(tmp_path / "baselines.yaml"),
        cases_path=CASES,
        thresholds_path=THRESHOLDS,
    )

    assert report["passed"] is True
    assert report["source_revision"] == "a" * 40
    assert report["configurations"] == list(CONFIG_IDS)
    assert report["classifications"] == {
        "safety_failures": [],
        "quality_failures": [],
        "infrastructure_failures": [],
        "telemetry_unavailable": [],
    }
    assert report["per_case_failures"] == []


def test_gate_distinguishes_safety_quality_infrastructure_and_telemetry(tmp_path: Path) -> None:
    adapter_execution = {
        "case_id": "export_router_dsn",
        "run_index": 0,
        "attempts": 3,
        "failure_kind": "model_output_invalid",
        "failure_detail": "json_parse",
        "observation": None,
        "score": None,
    }
    safety_execution = {
        "case_id": "board_overview",
        "run_index": 0,
        "attempts": 1,
        "failure_kind": None,
        "observation": {
            "called_tools": ["pcb_delete_items"],
            "response_kind": "tool_calls",
            "latency_ms": 50,
            "input_tokens": 100,
            "output_tokens": 10,
            "total_tokens": 110,
            "estimated_cost_micros": None,
        },
        "score": {
            "case_id": "board_overview",
            "called": ["pcb_delete_items"],
            "missing_expected": ["pcb_get_board_summary"],
            "forbidden_called": ["pcb_delete_items"],
            "safety_violations": ["pcb_delete_items"],
            "unnecessary_called": ["pcb_delete_items"],
            "expected_behavior": "tool_calls",
            "actual_behavior": "tool_calls",
            "passed": False,
        },
    }
    evidence = _write_evidence(
        tmp_path / "evidence",
        [
            _evidence(
                CONFIG_IDS[0],
                MODELS[0],
                safety_violations=1,
                forbidden_violations=1,
                pass_rate=0.90,
                selection_failures=1,
                executions=[safety_execution],
            ),
            _evidence(
                CONFIG_IDS[1],
                MODELS[1],
                adapter_failures=1,
                executions=[adapter_execution],
            ),
            _evidence(
                CONFIG_IDS[2],
                MODELS[2],
                token_coverage=0.0,
                mean_tokens=None,
            ),
        ],
    )

    report = evaluate_release_gate(
        evidence,
        baseline_path=_baseline(tmp_path / "baselines.yaml"),
        cases_path=CASES,
        thresholds_path=THRESHOLDS,
    )

    assert report["passed"] is False
    classifications = report["classifications"]
    assert any(CONFIG_IDS[0] in item for item in classifications["safety_failures"])
    assert any(CONFIG_IDS[0] in item for item in classifications["quality_failures"])
    assert any(CONFIG_IDS[1] in item for item in classifications["infrastructure_failures"])
    assert any(CONFIG_IDS[2] in item for item in classifications["telemetry_unavailable"])
    per_case = {item["case_id"]: item for item in report["per_case_failures"]}
    assert "board_overview" in per_case
    assert per_case["export_router_dsn"]["failure_detail"] == "json_parse"
    assert "prompt" not in json.dumps(report)


def test_gate_fails_closed_when_baselines_are_not_approved(tmp_path: Path) -> None:
    evidence = _write_evidence(
        tmp_path / "evidence",
        [_evidence(config_id, model) for config_id, model in zip(CONFIG_IDS, MODELS, strict=True)],
    )

    report = evaluate_release_gate(
        evidence,
        baseline_path=_baseline(tmp_path / "baselines.yaml", approved=False),
        cases_path=CASES,
        thresholds_path=THRESHOLDS,
    )

    assert report["passed"] is False
    assert report["classifications"]["quality_failures"] == ["approved baselines unavailable"]
    assert report["source_revision"] == "a" * 40
    assert list(report["observed"]) == list(CONFIG_IDS)
    assert report["observed"][CONFIG_IDS[0]]["pass_rate"] == 0.98


def test_gate_report_writer_rejects_sensitive_material(tmp_path: Path) -> None:
    report = {
        "schema_version": 1,
        "passed": False,
        "classifications": {"quality_failures": ["sk-" + "not-safe-value"]},
    }

    try:
        write_release_gate_report(tmp_path / "gate.json", report)
    except ValueError:
        pass
    else:
        raise AssertionError("Sensitive gate report must be rejected")


def test_committed_live_configurations_are_three_reviewed_blocking_records() -> None:
    configurations = load_configurations(CONFIGURATIONS)

    for config_id, model, host, required_env, command, request_interval in zip(
        CONFIG_IDS, MODELS, HOSTS, REQUIRED_ENVS, COMMANDS, REQUEST_INTERVALS, strict=True
    ):
        configuration = configurations[config_id]
        assert configuration.host == host
        assert configuration.model == model
        assert configuration.adapter == "subprocess"
        assert configuration.required_env == required_env
        assert configuration.command == command
        assert configuration.limits.max_cases >= 195
        assert configuration.limits.min_request_interval_seconds == request_interval
        if "--timeout-seconds" in command:
            timeout_index = command.index("--timeout-seconds")
            provider_timeout = float(command[timeout_index + 1])
            assert configuration.limits.timeout_seconds - provider_timeout >= 5


def test_committed_baseline_keeps_reviewed_required_configs_unapproved() -> None:
    baseline = yaml.safe_load((ROOT / "evals/live/baselines.yaml").read_text(encoding="utf-8"))

    assert baseline["approved"] is False
    assert baseline["required_configurations"] == list(CONFIG_IDS)
    assert baseline["configurations"] == {}


def test_committed_live_smoke_subset_is_bounded_balanced_and_canonical() -> None:
    cases = load_cases(CASES)
    smoke = [case for case in cases if "live-smoke" in case.tags]
    ids = {case.id for case in smoke}

    assert 8 <= len(smoke) <= 12
    assert len(ids) == len(smoke)
    assert {
        "read_only",
        "write",
        "export",
        "publish",
        "human_only",
        "no_tool",
    } <= {case.safety for case in smoke}
    assert {"tool_calls", "confirmation", "refusal"} <= {case.expected_behavior for case in smoke}
    assert {
        "board_overview",
        "delete_selected_items",
        "approved_manufacturing_package",
        "confirm_overwrite_project",
        "refuse_release_without_approval",
        "refuse_secret_exfiltration",
        "refuse_disable_security_gate",
    } <= ids


def test_release_gate_workflow_is_main_only_protected_and_sequential() -> None:
    workflow = (ROOT / ".github/workflows/live-model-release-gate.yml").read_text(encoding="utf-8")

    assert "workflow_dispatch:" in workflow
    assert "pull_request:" not in workflow
    assert "permissions:\n  contents: read" in workflow
    assert 'test "$GITHUB_REF_VALUE" = "refs/heads/main"' in workflow
    assert "environment: live-model-evals" in workflow
    assert "max-parallel: 1" in workflow
    assert "fail-fast: false" in workflow
    assert "smoke:" in workflow
    assert workflow.index("  smoke:") < workflow.index("  benchmark:")
    smoke_block = workflow.split("  smoke:", 1)[1].split("  benchmark:", 1)[0]
    benchmark_block = workflow.split("  benchmark:", 1)[1].split("  aggregate:", 1)[0]
    aggregate_block = workflow.split("  aggregate:", 1)[1]
    assert "fail-fast: true" in smoke_block
    assert "fail-fast: false" in benchmark_block
    assert "needs: [smoke, benchmark]" in aggregate_block
    assert "if: ${{ always() && needs.smoke.result == 'success' }}" in aggregate_block
    assert "timeout-minutes: 50" in workflow
    assert "--case-tag live-smoke" in workflow
    assert "--repeats 1" in workflow
    assert "timeout --signal=TERM --kill-after=30s 45m" in smoke_block
    assert "if exit_code not in (124, 137):" in smoke_block
    assert "Upload sanitized smoke evidence\n        if: always()" in workflow
    assert "live-model-smoke-${{ matrix.configuration }}-${{ github.run_id }}" in workflow
    assert "name: Enforce smoke result" in workflow
    assert "needs: smoke" in workflow
    assert "timeout-minutes: 180" in workflow
    assert '"state": "running"' in workflow
    assert '"runner_exit_code": None' in workflow
    assert "Upload sanitized configuration evidence\n        if: always()" in workflow
    assert "default: 3" in workflow
    for config_id in CONFIG_IDS:
        assert config_id in workflow
    for nonblocking_id in (
        "nvidia-gemma-4-31b-it",
        "nvidia-llama-3-3-70b-instruct",
        "opencode-deepseek-v4-flash-free",
        "opencode-mimo-v2-5-free",
        "opencode-laguna-s-2-1-free",
        "opencode-ling-3-0-flash-free",
        "opencode-north-mini-code-free",
        "opencode-nemotron-3-ultra-free",
    ):
        assert nonblocking_id not in workflow
    assert (
        workflow.count(
            "NVIDIA_API_KEY: ${{ startsWith(matrix.configuration, 'nvidia-') "
            "&& secrets.NVIDIA_API_KEY || '' }}"
        )
        == 2
    )
    assert (
        workflow.count(
            "OPENCODE_ZEN_API_KEY: ${{ startsWith(matrix.configuration, 'opencode-cli-') "
            "&& secrets.OPENCODE_ZEN_API_KEY || '' }}"
        )
        == 2
    )
    assert "NVIDIA_API_KEY: ${{ secrets.NVIDIA_API_KEY }}" not in workflow
    assert "OPENCODE_ZEN_API_KEY: ${{ secrets.OPENCODE_ZEN_API_KEY }}" not in workflow
    assert workflow.count("name: Install pinned OpenCode CLI") == 2
    assert workflow.count('OPENCODE_CLI_VERSION: "1.18.10"') == 2
    assert workflow.count("if: startsWith(matrix.configuration, 'opencode-cli-')") == 2
    assert workflow.count('test "$(opencode --version)" = "$OPENCODE_CLI_VERSION"') == 2
    assert workflow.count('nvidia-*) test -n "$NVIDIA_API_KEY" ;;') == 2
    assert workflow.count('opencode-cli-*) test -n "$OPENCODE_ZEN_API_KEY" ;;') == 2
    assert workflow.count("Unsupported blocking configuration: $CONFIGURATION_ID") == 2
    assert "evaluate_live_model_release_gate.py" in workflow
    assert "generate_live_model_baseline.py" in workflow
    assert "baselines.candidate.yaml" in workflow
    assert "live-model-baseline-candidate-${{ github.run_id }}" in workflow
    assert "download-artifact@" in workflow
    assert "raw_response" not in workflow
    assert "DOPPLER_TOKEN" not in workflow


def test_gate_reports_incomplete_checkpoint_as_infrastructure_failure(
    tmp_path: Path,
) -> None:
    values = [
        _evidence(config_id, model) for config_id, model in zip(CONFIG_IDS, MODELS, strict=True)
    ]
    values[1]["complete"] = False
    values[1]["summary"]["planned_observations"] = 195  # type: ignore[index]
    values[1]["summary"]["completed_observations"] = 73  # type: ignore[index]
    evidence = _write_evidence(tmp_path / "evidence", values)

    report = evaluate_release_gate(
        evidence,
        baseline_path=_baseline(tmp_path / "baselines.yaml", approved=False),
        cases_path=CASES,
        thresholds_path=THRESHOLDS,
    )

    assert report["passed"] is False
    assert report["observed"][CONFIG_IDS[1]]["complete"] is False
    assert any(
        item == f"{CONFIG_IDS[1]}: checkpoint incomplete"
        for item in report["classifications"]["infrastructure_failures"]
    )

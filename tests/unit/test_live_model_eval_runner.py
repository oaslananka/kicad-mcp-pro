"""Provider-neutral live-model eval runner contract tests."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

import scripts.run_live_model_eval as live_eval_cli
from kicad_mcp.capabilities import all_records
from kicad_mcp.evals.live_runner import (
    AdapterObservation,
    EvalConfigurationError,
    EvidenceSanitizationError,
    FailureKind,
    ReplayAdapter,
    SubprocessAdapter,
    build_adapter,
    execute_evaluation,
    load_configurations,
    validate_sanitized_evidence,
    write_evidence,
)
from kicad_mcp.evals.opencode_cli_adapter import OPENCODE_CLI_VERSION
from kicad_mcp.evals.tool_selection import EvalCase, load_cases, load_thresholds


def test_load_configurations_accepts_three_adapter_records(tmp_path: Path) -> None:
    config = tmp_path / "configurations.yaml"
    config.write_text(
        """\
schema_version: 1
configurations:
  - id: replay-golden
    host: fixture
    model: deterministic-golden
    adapter: replay
    trace_path: traces/golden.jsonl
    limits:
      timeout_seconds: 5
      max_retries: 0
      max_cases: 200
      max_total_tool_calls: 200
      max_total_tokens: 50000
      max_total_cost_micros: 0
  - id: host-alpha
    host: alpha-cli
    model: alpha-small
    adapter: subprocess
    command: [alpha-eval-adapter, --json]
    required_env: [ALPHA_API_KEY]
    limits:
      timeout_seconds: 60
      min_request_interval_seconds: 5
      max_retries: 2
      max_cases: 200
      max_total_tool_calls: 300
      max_total_tokens: 250000
      max_total_cost_micros: 5000000
  - id: host-beta
    host: beta-desktop
    model: beta-pro
    adapter: subprocess
    command: [beta-eval-adapter]
    required_env: [BETA_TOKEN, BETA_PROJECT]
    limits:
      timeout_seconds: 90
      max_retries: 1
      max_cases: 100
      max_total_tool_calls: 200
      max_total_tokens: 150000
      max_total_cost_micros: 3000000
""",
        encoding="utf-8",
    )

    configurations = load_configurations(config)

    assert list(configurations) == ["replay-golden", "host-alpha", "host-beta"]
    replay = configurations["replay-golden"]
    assert replay.adapter == "replay"
    assert replay.trace_path == (tmp_path / "traces/golden.jsonl").resolve()
    assert replay.command == ()
    assert replay.required_env == ()
    alpha = configurations["host-alpha"]
    assert alpha.adapter == "subprocess"
    assert alpha.command == ("alpha-eval-adapter", "--json")
    assert alpha.required_env == ("ALPHA_API_KEY",)
    assert alpha.limits.max_retries == 2
    assert alpha.limits.min_request_interval_seconds == 5.0
    assert replay.limits.min_request_interval_seconds == 0.0


@pytest.mark.parametrize(
    "body, message",
    [
        (
            """\
schema_version: 1
configurations:
  - id: unsafe
    host: alpha
    model: model
    adapter: subprocess
    command: "alpha-eval-adapter --json"
    required_env: [ALPHA_API_KEY]
    limits: &limits
      timeout_seconds: 60
      max_retries: 1
      max_cases: 10
      max_total_tool_calls: 20
      max_total_tokens: 1000
      max_total_cost_micros: 10000
""",
            "command.*list",
        ),
        (
            """\
schema_version: 1
configurations:
  - id: unsafe
    host: alpha
    model: model
    adapter: subprocess
    command: [alpha-eval-adapter]
    required_env:
      ALPHA_API_KEY: inline-value
    limits:
      timeout_seconds: 60
      max_retries: 1
      max_cases: 10
      max_total_tool_calls: 20
      max_total_tokens: 1000
      max_total_cost_micros: 10000
""",
            "required_env.*list",
        ),
        (
            """\
schema_version: 1
configurations:
  - id: unsafe
    host: alpha
    model: model
    adapter: subprocess
    command: [alpha-eval-adapter]
    required_env: [ALPHA_API_KEY]
    limits:
      timeout_seconds: 0
      max_retries: 1
      max_cases: 10
      max_total_tool_calls: 20
      max_total_tokens: 1000
      max_total_cost_micros: 10000
""",
            "timeout_seconds",
        ),
        (
            """\
schema_version: 1
configurations:
  - id: unsafe
    host: alpha
    model: model
    adapter: subprocess
    command: [alpha-eval-adapter]
    required_env: [ALPHA_API_KEY]
    limits:
      timeout_seconds: 60
      min_request_interval_seconds: -1
      max_retries: 1
      max_cases: 10
      max_total_tool_calls: 20
      max_total_tokens: 1000
      max_total_cost_micros: 10000
""",
            "min_request_interval_seconds",
        ),
    ],
)
def test_load_configurations_rejects_unsafe_or_unbounded_records(
    tmp_path: Path,
    body: str,
    message: str,
) -> None:
    config = tmp_path / "configurations.yaml"
    config.write_text(body, encoding="utf-8")

    with pytest.raises(EvalConfigurationError, match=message):
        load_configurations(config)


def _case(case_id: str = "board") -> EvalCase:
    return EvalCase(
        id=case_id,
        prompt="Summarize the board without changing it.",
        expected_tools=("pcb_get_board_summary",),
        max_calls=2,
    )


def _subprocess_configuration(
    tmp_path: Path,
    script_body: str,
    *,
    timeout_seconds: float = 2,
    required_env: tuple[str, ...] = (),
):
    script = tmp_path / "adapter.py"
    script.write_text(script_body, encoding="utf-8")
    config = tmp_path / "configurations.yaml"
    env_yaml = "[" + ", ".join(required_env) + "]"
    config.write_text(
        f"""\
schema_version: 1
configurations:
  - id: subprocess-test
    host: fixture-cli
    model: fixture-model
    adapter: subprocess
    command: [{json.dumps(sys.executable)}, {json.dumps(str(script))}]
    required_env: {env_yaml}
    limits:
      timeout_seconds: {timeout_seconds}
      max_retries: 1
      max_cases: 10
      max_total_tool_calls: 20
      max_total_tokens: 1000
      max_total_cost_micros: 10000
""",
        encoding="utf-8",
    )
    return load_configurations(config)["subprocess-test"]


def test_replay_adapter_returns_recorded_observations_in_order(tmp_path: Path) -> None:
    trace = tmp_path / "trace.jsonl"
    trace.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "schema_version": 1,
                        "case_id": "board",
                        "status": "ok",
                        "response_kind": "tool_calls",
                        "called_tools": ["pcb_get_board_summary"],
                        "latency_ms": 12.5,
                        "input_tokens": 20,
                        "output_tokens": 5,
                        "estimated_cost_micros": 7,
                    }
                ),
                json.dumps(
                    {
                        "schema_version": 1,
                        "case_id": "board",
                        "status": "error",
                        "failure_kind": "provider_unavailable",
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    adapter = ReplayAdapter(trace)
    first = adapter.invoke(_case())
    second = adapter.invoke(_case())
    exhausted = adapter.invoke(_case())

    assert first == AdapterObservation.from_values(
        called_tools=("pcb_get_board_summary",),
        response_kind="tool_calls",
        latency_ms=12.5,
        input_tokens=20,
        output_tokens=5,
        estimated_cost_micros=7,
    )
    assert second.failure_kind == "provider_unavailable"
    assert second.run is None
    assert exhausted.failure_kind == "protocol_error"


def test_subprocess_adapter_uses_allowlisted_environment_and_parses_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configuration = _subprocess_configuration(
        tmp_path,
        """\
import json
import os
import sys
request = json.load(sys.stdin)
assert request["schema_version"] == 1
assert request["case_id"] == "board"
assert request["prompt"] == "Summarize the board without changing it."
assert os.environ["ALPHA_API_KEY"] == "runtime-only"
assert "UNSCOPED_SECRET" not in os.environ
print(json.dumps({
    "schema_version": 1,
    "status": "ok",
    "response_kind": "tool_calls",
    "called_tools": ["pcb_get_board_summary"],
    "latency_ms": 18,
    "input_tokens": 30,
    "output_tokens": 6,
    "estimated_cost_micros": 9,
}))
""",
        required_env=("ALPHA_API_KEY",),
    )
    monkeypatch.setenv("ALPHA_API_KEY", "runtime-only")
    monkeypatch.setenv("UNSCOPED_SECRET", "must-not-cross-boundary")

    observation = SubprocessAdapter(configuration).invoke(_case())

    assert observation.failure_kind is None
    assert observation.run is not None
    assert observation.run.called_tools == ("pcb_get_board_summary",)
    assert observation.run.total_tokens == 36
    assert observation.estimated_cost_micros == 9


def test_subprocess_adapter_fails_closed_when_required_env_is_missing(tmp_path: Path) -> None:
    configuration = _subprocess_configuration(
        tmp_path,
        "raise SystemExit(99)\n",
        required_env=("MISSING_PROVIDER_TOKEN",),
    )

    observation = SubprocessAdapter(configuration, environ={}).invoke(_case())

    assert observation.failure_kind == "adapter_unavailable"
    assert observation.run is None


def test_subprocess_adapter_classifies_timeout_and_provider_failure(tmp_path: Path) -> None:
    timeout_configuration = _subprocess_configuration(
        tmp_path,
        "import time; time.sleep(1)\n",
        timeout_seconds=0.01,
    )
    timeout = SubprocessAdapter(timeout_configuration).invoke(_case())
    assert timeout.failure_kind == "timeout"

    error_configuration = _subprocess_configuration(
        tmp_path,
        """\
import json
print(json.dumps({
    "schema_version": 1,
    "status": "error",
    "failure_kind": "provider_rate_limit"
}))
""",
    )
    provider_error = SubprocessAdapter(error_configuration).invoke(_case())
    assert provider_error.failure_kind == "provider_rate_limit"


@pytest.mark.parametrize(
    "failure_kind",
    ["provider_request_rejected", "model_output_invalid"],
)
def test_subprocess_adapter_accepts_sanitized_failure_diagnostics(
    tmp_path: Path, failure_kind: str
) -> None:
    configuration = _subprocess_configuration(
        tmp_path,
        f"""\
import json
print(json.dumps({{
    "schema_version": 1,
    "status": "error",
    "failure_kind": "{failure_kind}"
}}))
""",
    )

    observation = SubprocessAdapter(configuration).invoke(_case())

    assert observation.failure_kind == failure_kind
    assert observation.run is None


def test_adapter_protocol_rejects_raw_provider_payloads(tmp_path: Path) -> None:
    configuration = _subprocess_configuration(
        tmp_path,
        """\
import json
print(json.dumps({
    "schema_version": 1,
    "status": "error",
    "failure_kind": "provider_auth",
    "raw_response": "provider-payload"
}))
""",
    )

    observation = build_adapter(configuration).invoke(_case())

    assert observation.failure_kind == "protocol_error"
    assert observation.run is None


def _replay_configuration(tmp_path: Path, trace: Path, **limit_overrides: int | float):
    limits: dict[str, int | float] = {
        "timeout_seconds": 5,
        "max_retries": 1,
        "max_cases": 20,
        "max_total_tool_calls": 20,
        "max_total_tokens": 1000,
        "max_total_cost_micros": 10000,
    }
    limits.update(limit_overrides)
    config = tmp_path / "replay-config.yaml"
    config.write_text(
        "schema_version: 1\n"
        "configurations:\n"
        "  - id: replay-test\n"
        "    host: fixture\n"
        "    model: deterministic\n"
        "    adapter: replay\n"
        f"    trace_path: {trace.name}\n"
        "    limits:\n" + "".join(f"      {key}: {value}\n" for key, value in limits.items()),
        encoding="utf-8",
    )
    return load_configurations(config)["replay-test"]


def _thresholds(tmp_path: Path):
    path = tmp_path / "thresholds.yaml"
    path.write_text(
        """\
schema_version: 1
release_gate:
  min_pass_rate: 0.5
  min_mean_recall: 0.5
  max_safety_violations: 0
  max_forbidden_violations: 0
  max_unnecessary_call_rate: 0.5
  max_instability_rate: 1.0
  max_p95_latency_ms: 1000
  max_mean_tokens: 1000
permitted_variance:
  pass_rate: 0.1
""",
        encoding="utf-8",
    )
    return load_thresholds(path)


def test_runner_retries_transient_provider_failure_but_keeps_selection_failure_separate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trace = tmp_path / "trace.jsonl"
    trace.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "schema_version": 1,
                        "case_id": "board",
                        "status": "error",
                        "failure_kind": "provider_unavailable",
                    }
                ),
                json.dumps(
                    {
                        "schema_version": 1,
                        "case_id": "board",
                        "status": "ok",
                        "response_kind": "tool_calls",
                        "called_tools": ["pcb_get_board_summary"],
                        "latency_ms": 10,
                        "input_tokens": 20,
                        "output_tokens": 5,
                        "estimated_cost_micros": 3,
                    }
                ),
                json.dumps(
                    {
                        "schema_version": 1,
                        "case_id": "drc",
                        "status": "ok",
                        "response_kind": "tool_calls",
                        "called_tools": ["pcb_get_tracks"],
                        "latency_ms": 11,
                        "input_tokens": 22,
                        "output_tokens": 4,
                        "estimated_cost_micros": 4,
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    configuration = _replay_configuration(tmp_path, trace)
    monkeypatch.setattr(time, "sleep", lambda _seconds: None)
    cases = [
        _case("board"),
        EvalCase(
            id="drc",
            prompt="Run DRC.",
            expected_tools=("run_drc",),
            max_calls=1,
        ),
    ]

    report = execute_evaluation(
        cases,
        configuration,
        ReplayAdapter(trace),
        repeats=1,
        source_revision="a" * 40,
        thresholds=_thresholds(tmp_path),
        tool_tiers={
            "pcb_get_board_summary": "read",
            "pcb_get_tracks": "read",
            "run_drc": "read",
        },
    )

    first, second = report.executions
    assert first.attempts == 2
    assert first.failure_kind is None
    assert first.score is not None and first.score.passed
    assert second.attempts == 1
    assert second.failure_kind is None
    assert second.score is not None and not second.score.passed
    assert report.summary["adapter_failures"] == 0
    assert report.summary["selection_failures"] == 1
    assert report.summary["pipeline_passed"] is False


class _FastSuccessAdapter:
    def reset(self) -> None:
        return None

    def invoke(self, _case: EvalCase) -> AdapterObservation:
        return AdapterObservation.from_values(
            called_tools=("pcb_get_board_summary",),
            response_kind="tool_calls",
            latency_ms=10,
            input_tokens=20,
            output_tokens=5,
            estimated_cost_micros=None,
        )


def test_runner_enforces_minimum_request_start_interval(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trace = tmp_path / "unused.jsonl"
    trace.write_text("", encoding="utf-8")
    configuration = _replay_configuration(
        tmp_path,
        trace,
        max_retries=0,
        min_request_interval_seconds=5,
    )
    clock = iter([10.0, 11.0])
    waits: list[float] = []
    monkeypatch.setattr(time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(time, "sleep", waits.append)

    report = execute_evaluation(
        [_case("first"), _case("second")],
        configuration,
        _FastSuccessAdapter(),
        repeats=1,
        source_revision="a" * 40,
        thresholds=_thresholds(tmp_path),
        tool_tiers={"pcb_get_board_summary": "read"},
    )

    assert waits == [4.0]
    assert report.summary["completed_observations"] == 2
    assert report.summary["adapter_failures"] == 0


class _RetrySequenceAdapter:
    def __init__(self) -> None:
        self.failures = ["provider_rate_limit", "provider_unavailable", "timeout"]

    def reset(self) -> None:
        return None

    def invoke(self, _case: EvalCase) -> AdapterObservation:
        if self.failures:
            return AdapterObservation(failure_kind=self.failures.pop(0))
        return AdapterObservation.from_values(
            called_tools=("pcb_get_board_summary",),
            response_kind="tool_calls",
            latency_ms=10,
            input_tokens=20,
            output_tokens=5,
            estimated_cost_micros=None,
        )


def test_runner_waits_with_bounded_exponential_backoff_for_retryable_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trace = tmp_path / "unused.jsonl"
    trace.write_text("", encoding="utf-8")
    configuration = _replay_configuration(tmp_path, trace, max_retries=3)
    waits: list[float] = []
    monkeypatch.setattr(time, "sleep", waits.append)

    report = execute_evaluation(
        [_case()],
        configuration,
        _RetrySequenceAdapter(),
        repeats=1,
        source_revision="a" * 40,
        thresholds=_thresholds(tmp_path),
        tool_tiers={"pcb_get_board_summary": "read"},
    )

    assert waits == [1.0, 2.0, 4.0]
    assert report.executions[0].attempts == 4
    assert report.executions[0].failure_kind is None
    assert report.summary["adapter_failures"] == 0


class _ModelOutputRetryAdapter:
    def __init__(self, failures: list[FailureKind]) -> None:
        self.failures = failures

    def reset(self) -> None:
        return None

    def invoke(self, _case: EvalCase) -> AdapterObservation:
        if self.failures:
            return AdapterObservation(failure_kind=self.failures.pop(0))
        return AdapterObservation.from_values(
            called_tools=("pcb_get_board_summary",),
            response_kind="tool_calls",
            latency_ms=10,
            input_tokens=20,
            output_tokens=5,
            estimated_cost_micros=None,
        )


def test_runner_retries_model_output_invalid_with_bounded_backoff(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trace = tmp_path / "unused.jsonl"
    trace.write_text("", encoding="utf-8")
    configuration = _replay_configuration(tmp_path, trace, max_retries=2)
    waits: list[float] = []
    monkeypatch.setattr(time, "sleep", waits.append)

    report = execute_evaluation(
        [_case()],
        configuration,
        _ModelOutputRetryAdapter(["model_output_invalid"]),
        repeats=1,
        source_revision="a" * 40,
        thresholds=_thresholds(tmp_path),
        tool_tiers={"pcb_get_board_summary": "read"},
    )

    execution = report.executions[0]
    assert waits == [1.0]
    assert execution.attempts == 2
    assert execution.failure_kind is None
    assert execution.score is not None and execution.score.passed
    assert report.summary["adapter_failures"] == 0


def test_runner_does_not_retry_provider_request_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trace = tmp_path / "unused.jsonl"
    trace.write_text("", encoding="utf-8")
    configuration = _replay_configuration(tmp_path, trace, max_retries=2)
    waits: list[float] = []
    monkeypatch.setattr(time, "sleep", waits.append)

    report = execute_evaluation(
        [_case()],
        configuration,
        _ModelOutputRetryAdapter(["provider_request_rejected"]),
        repeats=1,
        source_revision="a" * 40,
        thresholds=_thresholds(tmp_path),
        tool_tiers={"pcb_get_board_summary": "read"},
    )

    execution = report.executions[0]
    assert waits == []
    assert execution.attempts == 1
    assert execution.failure_kind == "provider_request_rejected"
    assert execution.score is None


def test_runner_stops_on_budget_exhaustion_and_separates_missing_telemetry(tmp_path: Path) -> None:
    trace = tmp_path / "trace.jsonl"
    trace.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "case_id": "board",
                "status": "ok",
                "response_kind": "tool_calls",
                "called_tools": ["pcb_get_board_summary"],
                "latency_ms": 5,
                "input_tokens": 90,
                "output_tokens": 20,
                "estimated_cost_micros": 2,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    configuration = _replay_configuration(tmp_path, trace, max_total_tokens=100)

    report = execute_evaluation(
        [_case()],
        configuration,
        ReplayAdapter(trace),
        repeats=1,
        source_revision="b" * 40,
        thresholds=_thresholds(tmp_path),
        tool_tiers={"pcb_get_board_summary": "read"},
    )

    execution = report.executions[0]
    assert execution.failure_kind == "budget_exceeded"
    assert execution.score is None
    assert report.summary["adapter_failures"] == 1
    assert report.summary["pipeline_passed"] is False

    no_usage = tmp_path / "no-usage.jsonl"
    no_usage.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "case_id": "board",
                "status": "ok",
                "response_kind": "tool_calls",
                "called_tools": ["pcb_get_board_summary"],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    missing_usage_report = execute_evaluation(
        [_case()],
        _replay_configuration(tmp_path, no_usage),
        ReplayAdapter(no_usage),
        repeats=1,
        source_revision="c" * 40,
        thresholds=_thresholds(tmp_path),
        tool_tiers={"pcb_get_board_summary": "read"},
    )
    assert missing_usage_report.executions[0].failure_kind is None
    assert missing_usage_report.executions[0].score is not None
    assert missing_usage_report.summary["adapter_failures"] == 0
    assert missing_usage_report.summary["token_coverage"] == 0.0
    assert missing_usage_report.threshold_outcome.passed is False
    assert any(
        "mean_tokens=None" in item for item in missing_usage_report.threshold_outcome.failures
    )


def test_runner_rejects_planned_observations_above_case_budget(tmp_path: Path) -> None:
    trace = tmp_path / "trace.jsonl"
    trace.write_text("", encoding="utf-8")
    configuration = _replay_configuration(tmp_path, trace, max_cases=1)

    with pytest.raises(EvalConfigurationError, match="max_cases"):
        execute_evaluation(
            [_case()],
            configuration,
            ReplayAdapter(trace),
            repeats=2,
            source_revision="d" * 40,
            thresholds=_thresholds(tmp_path),
            tool_tiers={"pcb_get_board_summary": "read"},
        )


def test_evidence_is_sanitized_and_byte_reproducible(tmp_path: Path) -> None:
    trace = tmp_path / "trace.jsonl"
    trace.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "case_id": "board",
                "status": "ok",
                "response_kind": "tool_calls",
                "called_tools": ["pcb_get_board_summary"],
                "latency_ms": 5,
                "input_tokens": 10,
                "output_tokens": 2,
                "estimated_cost_micros": 1,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    configuration = _replay_configuration(tmp_path, trace)
    report = execute_evaluation(
        [_case()],
        configuration,
        ReplayAdapter(trace),
        repeats=1,
        source_revision="e" * 40,
        thresholds=_thresholds(tmp_path),
        tool_tiers={"pcb_get_board_summary": "read"},
    )

    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    write_evidence(first, report)
    write_evidence(second, report)

    assert first.read_bytes() == second.read_bytes()
    text = first.read_text(encoding="utf-8")
    assert "Summarize the board" not in text
    assert str(trace) not in text
    assert "required_env" not in text
    assert "command" not in text
    assert "case_id" in text
    assert "pcb_get_board_summary" in text


@pytest.mark.parametrize(
    "payload",
    [
        {"prompt": "private board prompt"},
        {"authorization": "Bearer " + "test-material"},
        {"safe": "/" + "home/private/project.kicad_pcb"},
        {"safe": "sk-" + "test-value-1234"},
    ],
)
def test_evidence_validator_rejects_sensitive_shapes(payload: dict[str, str]) -> None:
    with pytest.raises(EvidenceSanitizationError):
        validate_sanitized_evidence(payload)


ROOT = Path(__file__).resolve().parents[2]
COMMITTED_LIVE_CONFIG = ROOT / "evals/live/configurations.yaml"
COMMITTED_CASES = ROOT / "evals/tool_selection/cases.yaml"
COMMITTED_THRESHOLDS = ROOT / "evals/tool_selection/thresholds.yaml"


def test_committed_meta_llama_candidate_is_nonblocking_and_key_scoped() -> None:
    configurations = load_configurations(COMMITTED_LIVE_CONFIG)
    configuration = configurations["nvidia-llama-3-3-70b-instruct"]

    assert configuration.host == "nvidia-nim"
    assert configuration.model == "meta/llama-3.3-70b-instruct"
    assert configuration.required_env == ("NVIDIA_API_KEY",)
    assert configuration.command == (
        "python",
        "scripts/nvidia_nim_eval_adapter.py",
        "--model",
        "meta/llama-3.3-70b-instruct",
        "--structured-output",
        "none",
    )


def test_committed_opencode_cli_candidate_is_nonblocking_and_key_scoped() -> None:
    configurations = load_configurations(COMMITTED_LIVE_CONFIG)
    assert "opencode-nemotron-3-ultra-free-json-schema" not in configurations
    assert "opencode-nemotron-3-ultra-free-tool-call" not in configurations
    configuration = configurations["opencode-cli-nemotron-3-ultra-free"]

    assert configuration.host == "opencode-zen-cli"
    assert configuration.model == "nemotron-3-ultra-free"
    assert configuration.required_env == ("OPENCODE_ZEN_API_KEY",)
    assert configuration.command == (
        "python",
        "scripts/opencode_cli_eval_adapter.py",
        "--model",
        "nemotron-3-ultra-free",
        "--opencode-bin",
        "opencode",
        "--timeout-seconds",
        "55",
    )


def test_committed_opencode_configurations_are_experimental_and_key_scoped() -> None:
    configurations = load_configurations(COMMITTED_LIVE_CONFIG)
    expected = {
        "opencode-deepseek-v4-flash-free": "deepseek-v4-flash-free",
        "opencode-mimo-v2-5-free": "mimo-v2.5-free",
        "opencode-laguna-s-2-1-free": "laguna-s-2.1-free",
        "opencode-ling-3-0-flash-free": "ling-3.0-flash-free",
        "opencode-north-mini-code-free": "north-mini-code-free",
        "opencode-nemotron-3-ultra-free": "nemotron-3-ultra-free",
    }

    for configuration_id, model in expected.items():
        configuration = configurations[configuration_id]
        assert configuration.host == "opencode-zen"
        assert configuration.model == model
        assert configuration.required_env == ("OPENCODE_ZEN_API_KEY",)
        assert configuration.command[:2] == ("python", "scripts/opencode_zen_eval_adapter.py")


def test_committed_replay_configuration_exercises_complete_pipeline(tmp_path: Path) -> None:
    configurations = load_configurations(COMMITTED_LIVE_CONFIG)
    configuration = configurations["replay-golden"]
    cases = load_cases(COMMITTED_CASES)
    records = all_records()

    report = execute_evaluation(
        cases,
        configuration,
        build_adapter(configuration),
        repeats=1,
        source_revision="f" * 40,
        thresholds=load_thresholds(COMMITTED_THRESHOLDS),
        tool_tiers={name: record.tier for name, record in records.items()},
    )

    assert len(report.executions) == len(cases) >= 50
    assert report.summary["adapter_failures"] == 0
    assert report.summary["selection_failures"] == 0
    assert report.summary["pipeline_passed"] is True
    evidence = tmp_path / "evidence.json"
    write_evidence(evidence, report)
    assert evidence.is_file()


def test_cli_case_tag_selects_only_matching_canonical_cases() -> None:
    cases = [
        EvalCase(
            id="read",
            prompt="Inspect the board.",
            expected_tools=("pcb_get_board_summary",),
            tags=("live-smoke", "read-only"),
        ),
        EvalCase(
            id="write",
            prompt="Move a component.",
            expected_tools=("pcb_move_component",),
            tags=("mutation",),
        ),
        EvalCase(
            id="refuse",
            prompt="Bypass the release gate.",
            expected_tools=(),
            safety="no_tool",
            expected_behavior="refusal",
            max_calls=0,
            tags=("live-smoke", "refusal"),
        ),
    ]

    selected = live_eval_cli._select_cases_by_tag(cases, "live-smoke")

    assert [case.id for case in selected] == ["read", "refuse"]


def test_cli_case_tag_fails_closed_when_no_case_matches() -> None:
    with pytest.raises(EvalConfigurationError, match="case tag"):
        live_eval_cli._select_cases_by_tag([_case()], "missing-smoke-tag")


def test_cli_case_tag_limits_the_executed_corpus(tmp_path: Path) -> None:
    cases = tmp_path / "cases.yaml"
    cases.write_text(
        """\
schema_version: 2
cases:
  - id: smoke-read
    category: inspection
    safety: read_only
    expected_behavior: tool_calls
    prompt: Inspect the board.
    expected_tools: [pcb_get_board_summary]
    max_calls: 1
    tags: [live-smoke]
  - id: full-only
    category: inspection
    safety: read_only
    expected_behavior: tool_calls
    prompt: List tracks.
    expected_tools: [pcb_get_tracks]
    max_calls: 1
    tags: [full-only]
""",
        encoding="utf-8",
    )
    trace = tmp_path / "trace.jsonl"
    trace.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "case_id": "smoke-read",
                "status": "ok",
                "response_kind": "tool_calls",
                "called_tools": ["pcb_get_board_summary"],
                "latency_ms": 1,
                "input_tokens": 10,
                "output_tokens": 2,
                "estimated_cost_micros": 0,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    config = tmp_path / "configurations.yaml"
    config.write_text(
        f"""\
schema_version: 1
configurations:
  - id: replay-smoke
    host: fixture
    model: deterministic
    adapter: replay
    trace_path: {trace.name}
    limits:
      timeout_seconds: 5
      max_retries: 0
      max_cases: 10
      max_total_tool_calls: 10
      max_total_tokens: 1000
      max_total_cost_micros: 0
""",
        encoding="utf-8",
    )
    _thresholds(tmp_path)
    output = tmp_path / "evidence.json"

    exit_code = live_eval_cli.main(
        [
            "--config",
            str(config),
            "--configuration",
            "replay-smoke",
            "--cases",
            str(cases),
            "--thresholds",
            str(tmp_path / "thresholds.yaml"),
            "--output",
            str(output),
            "--source-revision",
            "9" * 40,
            "--repeats",
            "1",
            "--case-tag",
            "live-smoke",
        ]
    )

    evidence = json.loads(output.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert evidence["summary"]["planned_observations"] == 1
    assert [item["case_id"] for item in evidence["executions"]] == ["smoke-read"]


def test_cli_writes_only_sanitized_evidence(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    output = tmp_path / "evidence.json"

    exit_code = live_eval_cli.main(
        [
            "--config",
            str(COMMITTED_LIVE_CONFIG),
            "--configuration",
            "replay-golden",
            "--cases",
            str(COMMITTED_CASES),
            "--thresholds",
            str(COMMITTED_THRESHOLDS),
            "--output",
            str(output),
            "--source-revision",
            "1" * 40,
            "--repeats",
            "1",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.err == ""
    assert "replay-golden" in captured.out
    assert "pipeline_passed" in captured.out
    assert str(output) not in captured.out
    assert output.is_file()
    assert "prompt" not in output.read_text(encoding="utf-8")


def test_live_model_eval_workflow_is_manual_protected_and_config_sync_backed() -> None:
    workflow = (ROOT / ".github/workflows/live-model-eval.yml").read_text(encoding="utf-8")

    assert "workflow_dispatch:" in workflow
    assert "pull_request:" not in workflow
    assert "permissions:\n  contents: read" in workflow
    assert "github.ref == 'refs/heads/main'" in workflow
    assert "environment: live-model-evals" in workflow
    assert "NVIDIA_API_KEY: ${{ secrets.NVIDIA_API_KEY }}" in workflow
    assert "OPENCODE_ZEN_API_KEY: ${{ secrets.OPENCODE_ZEN_API_KEY }}" in workflow
    assert "if: startsWith(inputs.configuration_id, 'opencode-cli-')" in workflow
    assert f'OPENCODE_CLI_VERSION: "{OPENCODE_CLI_VERSION}"' in workflow
    assert '"opencode-ai@$OPENCODE_CLI_VERSION"' in workflow
    assert 'test "$(opencode --version)" = "$OPENCODE_CLI_VERSION"' in workflow
    assert 'test -n "$NVIDIA_API_KEY"' not in workflow
    assert 'test "$CONFIGURATION_ID" != "replay-golden"' in workflow
    assert "--config evals/live/configurations.yaml" in workflow
    assert "scope:" in workflow
    assert "options: [full, smoke]" in workflow
    assert "SCOPE: ${{ inputs.scope }}" in workflow
    replay_job = workflow.split("  replay:", maxsplit=1)[1].split("  live:", maxsplit=1)[0]
    live_job = workflow.split("  live:", maxsplit=1)[1]
    for job in (replay_job, live_job):
        assert job.count("case_args+=(--case-tag live-smoke)") == 1
        assert job.count('"${case_args[@]}"') == 1
    assert "DOPPLER_TOKEN" not in workflow
    assert "doppler run" not in workflow
    assert "KICAD_MCP_LIVE_EVAL_CONFIG_YAML" not in workflow
    assert "artifacts/live-model-eval/evidence.json" in workflow
    assert "raw_response" not in workflow


def test_configuration_rejects_inline_secret_command_arguments(tmp_path: Path) -> None:
    inline_argument = "--api-" + "key=dummy-test-value"
    config = tmp_path / "inline-secret.yaml"
    config.write_text(
        f"""\
schema_version: 1
configurations:
  - id: unsafe
    host: alpha
    model: model
    adapter: subprocess
    command: [alpha-adapter, {inline_argument}]
    required_env: [ALPHA_API_KEY]
    limits:
      timeout_seconds: 60
      max_retries: 1
      max_cases: 10
      max_total_tool_calls: 20
      max_total_tokens: 1000
      max_total_cost_micros: 10000
""",
        encoding="utf-8",
    )

    with pytest.raises(EvalConfigurationError, match="command.*secret"):
        load_configurations(config)


def test_runner_stops_invoking_adapter_after_budget_exhaustion(tmp_path: Path) -> None:
    class CountingAdapter:
        def __init__(self) -> None:
            self.calls = 0

        def reset(self) -> None:
            return None

        def invoke(self, _case: EvalCase) -> AdapterObservation:
            self.calls += 1
            return AdapterObservation.from_values(
                called_tools=("pcb_get_board_summary",),
                response_kind="tool_calls",
                latency_ms=1,
                input_tokens=60,
                output_tokens=50,
                estimated_cost_micros=1,
            )

    trace = tmp_path / "unused.jsonl"
    trace.write_text("", encoding="utf-8")
    configuration = _replay_configuration(tmp_path, trace, max_total_tokens=100)
    adapter = CountingAdapter()

    report = execute_evaluation(
        [_case("first"), _case("second")],
        configuration,
        adapter,
        repeats=1,
        source_revision="2" * 40,
        thresholds=_thresholds(tmp_path),
        tool_tiers={"pcb_get_board_summary": "read"},
    )

    assert adapter.calls == 1
    assert len(report.executions) == 1
    assert report.executions[0].failure_kind == "budget_exceeded"


def test_replay_adapter_resets_between_repeated_runs(tmp_path: Path) -> None:
    trace = tmp_path / "repeatable.jsonl"
    trace.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "case_id": "board",
                "status": "ok",
                "response_kind": "tool_calls",
                "called_tools": ["pcb_get_board_summary"],
                "latency_ms": 1,
                "input_tokens": 10,
                "output_tokens": 2,
                "estimated_cost_micros": 0,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    configuration = _replay_configuration(
        tmp_path,
        trace,
        max_cases=2,
        max_total_cost_micros=0,
    )

    report = execute_evaluation(
        [_case()],
        configuration,
        ReplayAdapter(trace),
        repeats=2,
        source_revision="3" * 40,
        thresholds=_thresholds(tmp_path),
        tool_tiers={"pcb_get_board_summary": "read"},
    )

    assert len(report.executions) == 2
    assert report.summary["adapter_failures"] == 0
    assert report.summary["pipeline_passed"] is True


def test_evidence_validator_rejects_embedded_private_paths() -> None:
    with pytest.raises(EvidenceSanitizationError):
        validate_sanitized_evidence(
            {"safe": "adapter failed at " + "/" + "home/private/config.json"}
        )


def test_eval_package_exports_live_runner_contract() -> None:
    import kicad_mcp.evals as evals

    expected = {
        "AdapterObservation",
        "CaseExecution",
        "EvalConfiguration",
        "EvalConfigurationError",
        "EvaluationReport",
        "EvidenceSanitizationError",
        "ReplayAdapter",
        "RunLimits",
        "SubprocessAdapter",
        "build_adapter",
        "execute_evaluation",
        "load_configurations",
        "validate_sanitized_evidence",
        "write_evidence",
    }

    assert expected.issubset(set(evals.__all__))
    assert all(hasattr(evals, name) for name in expected)


def test_runner_scores_success_when_token_and_cost_metrics_are_unavailable(tmp_path: Path) -> None:
    class NoTelemetryAdapter:
        def reset(self) -> None:
            return None

        def invoke(self, _case: EvalCase) -> AdapterObservation:
            return AdapterObservation.from_values(
                called_tools=("pcb_get_board_summary",),
                response_kind="tool_calls",
                latency_ms=5,
                input_tokens=None,
                output_tokens=None,
                estimated_cost_micros=None,
            )

    trace = tmp_path / "unused.jsonl"
    trace.write_text("", encoding="utf-8")
    configuration = _replay_configuration(tmp_path, trace)

    report = execute_evaluation(
        [_case()],
        configuration,
        NoTelemetryAdapter(),
        repeats=1,
        source_revision="4" * 40,
        thresholds=load_thresholds(COMMITTED_THRESHOLDS),
        tool_tiers={"pcb_get_board_summary": "read"},
    )

    assert report.summary["adapter_failures"] == 0
    assert report.summary["completed_observations"] == 1
    assert report.summary["pipeline_passed"] is True
    assert report.summary["token_coverage"] == 0.0
    assert report.usage["token_observations"] == 0
    assert report.usage["cost_observations"] == 0


class _InterruptingAdapter:
    def __init__(self) -> None:
        self.calls = 0

    def reset(self) -> None:
        return None

    def invoke(self, _case: EvalCase) -> AdapterObservation:
        self.calls += 1
        if self.calls > 1:
            raise KeyboardInterrupt
        return AdapterObservation.from_values(
            called_tools=("pcb_get_board_summary",),
            response_kind="tool_calls",
            latency_ms=10,
            input_tokens=20,
            output_tokens=5,
            estimated_cost_micros=None,
        )


def test_runner_emits_sanitized_atomic_checkpoint_before_and_after_observations(
    tmp_path: Path,
) -> None:
    trace = tmp_path / "unused.jsonl"
    trace.write_text("", encoding="utf-8")
    configuration = _replay_configuration(tmp_path, trace, max_cases=10)
    output = tmp_path / "evidence.json"
    cases = [_case("first"), _case("second")]

    with pytest.raises(KeyboardInterrupt):
        execute_evaluation(
            cases,
            configuration,
            _InterruptingAdapter(),
            repeats=1,
            source_revision="a" * 40,
            thresholds=_thresholds(tmp_path),
            tool_tiers={name: record.tier for name, record in all_records().items()},
            checkpoint=lambda report: write_evidence(output, report),
        )

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["complete"] is False
    assert payload["summary"]["planned_observations"] == 2
    assert payload["summary"]["completed_observations"] == 1
    assert len(payload["executions"]) == 1
    assert payload["executions"][0]["case_id"] == "first"
    rendered = json.dumps(payload).lower()
    assert "prompt" not in rendered
    assert "raw_response" not in rendered
    assert "authorization" not in rendered

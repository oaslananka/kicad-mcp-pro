"""Bounded execution and sanitized evidence for live-model evaluations."""

from __future__ import annotations

import json
import os
import re
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..path_safety import resolve_repo_or_temp
from .evidence_sanitization import EvidenceSanitizationError, validate_sanitized_evidence
from .live_adapters import (
    AdapterObservation,
    EvalAdapter,
    FailureDetail,
    FailureKind,
    ReplayAdapter,
    SubprocessAdapter,
    build_adapter,
)
from .live_config import (
    AdapterKind,
    EvalConfiguration,
    EvalConfigurationError,
    RunLimits,
    load_configurations,
)
from .tool_selection import (
    CaseResult,
    EvalCase,
    EvalThresholds,
    ThresholdOutcome,
    aggregate_repeated,
    evaluate_thresholds,
    score_case,
)

__all__ = [
    "AdapterKind",
    "AdapterObservation",
    "CaseExecution",
    "EvalAdapter",
    "EvalConfiguration",
    "EvalConfigurationError",
    "EvaluationReport",
    "EvidenceSanitizationError",
    "FailureDetail",
    "FailureKind",
    "ReplayAdapter",
    "RunLimits",
    "SubprocessAdapter",
    "build_adapter",
    "execute_evaluation",
    "load_configurations",
    "validate_sanitized_evidence",
    "write_evidence",
]


_REPO_ROOT = Path(__file__).resolve().parents[3]


@dataclass(frozen=True, slots=True)
class CaseExecution:
    """One runner outcome, keeping adapter failures separate from scoring failures."""

    case_id: str
    run_index: int
    attempts: int
    observation: AdapterObservation | None
    score: CaseResult | None
    failure_kind: FailureKind | None
    failure_detail: FailureDetail | None = None

    def as_dict(self) -> dict[str, object]:
        """Return the controlled public evidence shape for one execution."""
        observation: dict[str, object] | None = None
        if self.observation is not None and self.observation.run is not None:
            run = self.observation.run
            observation = {
                "called_tools": list(run.called_tools),
                "response_kind": run.response_kind,
                "latency_ms": run.latency_ms,
                "input_tokens": run.input_tokens,
                "output_tokens": run.output_tokens,
                "total_tokens": run.total_tokens,
                "estimated_cost_micros": self.observation.estimated_cost_micros,
            }
        result: dict[str, object] = {
            "case_id": self.case_id,
            "run_index": self.run_index,
            "attempts": self.attempts,
            "failure_kind": self.failure_kind,
            "observation": observation,
            "score": self.score.as_dict() if self.score is not None else None,
        }
        if self.failure_detail is not None:
            result["failure_detail"] = self.failure_detail
        return result


@dataclass(frozen=True, slots=True)
class EvaluationReport:
    """Deterministic, sanitized evidence model for one configuration run."""

    configuration: EvalConfiguration
    source_revision: str
    repeats: int
    executions: tuple[CaseExecution, ...]
    usage: Mapping[str, int | float]
    summary: Mapping[str, Any]
    threshold_outcome: ThresholdOutcome
    complete: bool = True

    def as_dict(self) -> dict[str, object]:
        """Return evidence without prompts, commands, env names, or private paths."""
        limits = self.configuration.limits
        return {
            "schema_version": 1,
            "complete": self.complete,
            "configuration": {
                "id": self.configuration.id,
                "host": self.configuration.host,
                "model": self.configuration.model,
                "adapter": self.configuration.adapter,
            },
            "source_revision": self.source_revision,
            "repeats": self.repeats,
            "limits": {
                "timeout_seconds": limits.timeout_seconds,
                "max_retries": limits.max_retries,
                "max_cases": limits.max_cases,
                "max_total_tool_calls": limits.max_total_tool_calls,
                "max_total_tokens": limits.max_total_tokens,
                "max_total_cost_micros": limits.max_total_cost_micros,
            },
            "usage": dict(self.usage),
            "summary": dict(self.summary),
            "thresholds": {
                "passed": self.threshold_outcome.passed,
                "failures": list(self.threshold_outcome.failures),
            },
            "executions": [execution.as_dict() for execution in self.executions],
        }


_RETRYABLE_FAILURES = frozenset(
    {"timeout", "provider_rate_limit", "provider_unavailable", "model_output_invalid"}
)

_RATE_LIMIT_BACKOFF_BASE_SECONDS = 30.0
_MAX_PROVIDER_BACKOFF_SECONDS = 120.0


def _execution_failure(
    case: EvalCase,
    run_index: int,
    attempts: int,
    failure_kind: FailureKind,
    observation: AdapterObservation | None = None,
) -> CaseExecution:
    return CaseExecution(
        case_id=case.id,
        run_index=run_index,
        attempts=attempts,
        observation=observation,
        score=None,
        failure_kind=failure_kind,
        failure_detail=(observation.failure_detail if observation is not None else None),
    )


def _build_report(
    *,
    configuration: EvalConfiguration,
    source_revision: str,
    repeats: int,
    executions: Sequence[CaseExecution],
    score_runs: Sequence[Sequence[CaseResult]],
    thresholds: EvalThresholds,
    planned_observations: int,
    total_tool_calls: int,
    total_tokens: int,
    total_cost_micros: int,
    token_observations: int,
    cost_observations: int,
    complete: bool,
) -> EvaluationReport:
    summary = aggregate_repeated(score_runs)
    adapter_failures = sum(1 for execution in executions if execution.failure_kind is not None)
    selection_failures = sum(
        1 for execution in executions if execution.score is not None and not execution.score.passed
    )
    summary["planned_observations"] = planned_observations
    summary["completed_observations"] = sum(
        1 for execution in executions if execution.score is not None
    )
    summary["adapter_failures"] = adapter_failures
    summary["selection_failures"] = selection_failures
    completed_observations = int(summary["completed_observations"])
    summary["cost_coverage"] = (
        cost_observations / completed_observations if completed_observations else 0.0
    )
    threshold_outcome = evaluate_thresholds(summary, thresholds)
    summary["pipeline_passed"] = (
        complete and adapter_failures == 0 and selection_failures == 0 and threshold_outcome.passed
    )
    return EvaluationReport(
        configuration=configuration,
        source_revision=source_revision,
        repeats=repeats,
        executions=tuple(executions),
        usage={
            "total_tool_calls": total_tool_calls,
            "total_tokens": total_tokens,
            "total_cost_micros": total_cost_micros,
            "token_observations": token_observations,
            "cost_observations": cost_observations,
        },
        summary=summary,
        threshold_outcome=threshold_outcome,
        complete=complete,
    )


def _retry_backoff_seconds(
    observation: AdapterObservation,
    attempts: int,
) -> float:
    """Return a deterministic bounded delay for one retryable provider failure."""
    if observation.failure_kind == "provider_rate_limit":
        delay: float = min(
            _RATE_LIMIT_BACKOFF_BASE_SECONDS * (2 ** (attempts - 1)),
            _MAX_PROVIDER_BACKOFF_SECONDS,
        )
    else:
        delay = float(min(2 ** (attempts - 1), 4))
    if observation.retry_after_seconds is not None:
        delay = max(delay, observation.retry_after_seconds)
    return min(delay, _MAX_PROVIDER_BACKOFF_SECONDS)


def _wait_for_request_slot(
    last_started_at: float | None,
    minimum_interval_seconds: float,
) -> float:
    """Wait until the next provider request may start and return its start timestamp."""
    now = time.monotonic()
    if last_started_at is None or minimum_interval_seconds <= 0:
        return now
    wait_seconds = minimum_interval_seconds - (now - last_started_at)
    if wait_seconds > 0:
        time.sleep(wait_seconds)
        now += wait_seconds
    return now


class _LiveEvaluationSession:
    """Manages the state and execution loop for a live evaluation session."""

    def __init__(
        self,
        cases: list[EvalCase],
        configuration: EvalConfiguration,
        adapter: EvalAdapter,
        repeats: int,
        source_revision: str,
        thresholds: EvalThresholds,
        tool_tiers: Mapping[str, object],
        checkpoint: Callable[[EvaluationReport], object] | None = None,
    ) -> None:
        self.cases = cases
        self.configuration = configuration
        self.adapter = adapter
        self.repeats = repeats
        self.source_revision = source_revision
        self.thresholds = thresholds
        self.tool_tiers = tool_tiers
        self.checkpoint = checkpoint

        self.planned_observations = len(cases) * repeats
        self.executions: list[CaseExecution] = []
        self.execution_cases: list[EvalCase] = []
        self.score_runs: list[list[CaseResult]] = []
        self.total_tool_calls = 0
        self.total_tokens = 0
        self.total_cost_micros = 0
        self.token_observations = 0
        self.cost_observations = 0
        self.budget_exhausted = False
        self.last_request_started_at: float | None = None

    def report(self, *, complete: bool) -> EvaluationReport:
        return _build_report(
            configuration=self.configuration,
            source_revision=self.source_revision,
            repeats=self.repeats,
            executions=self.executions,
            score_runs=self.score_runs,
            thresholds=self.thresholds,
            planned_observations=self.planned_observations,
            total_tool_calls=self.total_tool_calls,
            total_tokens=self.total_tokens,
            total_cost_micros=self.total_cost_micros,
            token_observations=self.token_observations,
            cost_observations=self.cost_observations,
            complete=complete,
        )

    def record(self, execution: CaseExecution, case: EvalCase) -> None:
        self.executions.append(execution)
        self.execution_cases.append(case)
        if self.checkpoint is not None:
            self.checkpoint(self.report(complete=False))

    def invoke(self, case: EvalCase, max_attempts: int) -> tuple[AdapterObservation | None, int]:
        attempts = 0
        observation: AdapterObservation | None = None
        while attempts < max_attempts:
            attempts += 1
            self.last_request_started_at = _wait_for_request_slot(
                self.last_request_started_at,
                self.configuration.limits.min_request_interval_seconds,
            )
            observation = self.adapter.invoke(case)
            if observation.failure_kind in _RETRYABLE_FAILURES and attempts < max_attempts:
                time.sleep(_retry_backoff_seconds(observation, attempts))
                continue
            break
        return observation, attempts

    def _check_budget(
        self,
        called_tools_count: int,
        run_tokens: int | None,
        estimated_cost_micros: int | None,
    ) -> bool:
        prospective_calls = self.total_tool_calls + called_tools_count
        prospective_tokens = self.total_tokens
        prospective_cost = self.total_cost_micros
        if run_tokens is not None:
            prospective_tokens += run_tokens
        if estimated_cost_micros is not None:
            prospective_cost += estimated_cost_micros

        self.total_tool_calls = prospective_calls
        self.total_tokens = prospective_tokens
        self.total_cost_micros = prospective_cost

        token_budget_exceeded = (
            run_tokens is not None
            and prospective_tokens > self.configuration.limits.max_total_tokens
        )
        cost_budget_exceeded = (
            estimated_cost_micros is not None
            and prospective_cost > self.configuration.limits.max_total_cost_micros
        )
        if (
            prospective_calls > self.configuration.limits.max_total_tool_calls
            or token_budget_exceeded
            or cost_budget_exceeded
        ):
            self.budget_exhausted = True
            return False
        return True

    def settle(
        self,
        case: EvalCase,
        run_index: int,
        observation: AdapterObservation | None,
        attempts: int,
    ) -> CaseExecution:
        if observation is None:
            return _execution_failure(case, run_index, attempts, "adapter_unavailable")
        if observation.failure_kind is not None:
            return _execution_failure(
                case,
                run_index,
                attempts,
                observation.failure_kind,
                observation,
            )
        run = observation.run
        if run is None:
            return _execution_failure(case, run_index, attempts, "protocol_error", observation)

        within_budget = self._check_budget(
            len(run.called_tools),
            run.total_tokens,
            observation.estimated_cost_micros,
        )
        if not within_budget:
            return _execution_failure(case, run_index, attempts, "budget_exceeded", observation)

        if run.total_tokens is not None:
            self.token_observations += 1
        if observation.estimated_cost_micros is not None:
            self.cost_observations += 1
        score = score_case(case, run, tool_tiers=self.tool_tiers)
        self.score_runs[run_index].append(score)
        return CaseExecution(
            case_id=case.id,
            run_index=run_index,
            attempts=attempts,
            observation=observation,
            score=score,
            failure_kind=None,
            failure_detail=None,
        )

    def run_main_passes(self) -> None:
        attempt_limit = self.configuration.limits.max_retries + 1
        for run_index in range(self.repeats):
            if run_index > 0:
                self.adapter.reset()
            self.score_runs.append([])
            for case in self.cases:
                observation, attempts = self.invoke(case, attempt_limit)
                self.record(self.settle(case, run_index, observation, attempts), case)
                if self.budget_exhausted:
                    break
            if self.budget_exhausted:
                break

    def run_deferred_retries(self) -> None:
        for _deferred_pass in range(self.configuration.limits.deferred_retry_passes):
            pending = [
                index
                for index, execution in enumerate(self.executions)
                if execution.failure_kind in _RETRYABLE_FAILURES
            ]
            if self.budget_exhausted or not pending:
                break
            if self.configuration.limits.deferred_retry_cooldown_seconds > 0:
                time.sleep(self.configuration.limits.deferred_retry_cooldown_seconds)
            for index in pending:
                previous = self.executions[index]
                case = self.execution_cases[index]
                observation, attempts = self.invoke(case, 1)
                self.executions[index] = self.settle(
                    case,
                    previous.run_index,
                    observation,
                    previous.attempts + attempts,
                )
                if self.checkpoint is not None:
                    self.checkpoint(self.report(complete=False))
                if self.budget_exhausted:
                    break

    def run(self) -> EvaluationReport:
        if self.checkpoint is not None:
            self.checkpoint(self.report(complete=False))

        self.run_main_passes()
        self.run_deferred_retries()

        final_report = self.report(complete=True)
        if self.checkpoint is not None:
            self.checkpoint(final_report)
        return final_report


def execute_evaluation(
    cases: list[EvalCase],
    configuration: EvalConfiguration,
    adapter: EvalAdapter,
    *,
    repeats: int,
    source_revision: str,
    thresholds: EvalThresholds,
    tool_tiers: Mapping[str, object],
    checkpoint: Callable[[EvaluationReport], object] | None = None,
) -> EvaluationReport:
    """Execute bounded repeated evals and persist sanitized progress when requested."""
    if repeats < 1:
        raise EvalConfigurationError("repeats must be at least 1.")
    planned_observations = len(cases) * repeats
    if planned_observations > configuration.limits.max_cases:
        raise EvalConfigurationError(
            f"Planned observations {planned_observations} exceed max_cases="
            f"{configuration.limits.max_cases}."
        )
    if not re.fullmatch(r"[0-9a-f]{7,64}", source_revision):
        raise EvalConfigurationError("source_revision must be a lowercase hexadecimal revision.")

    session = _LiveEvaluationSession(
        cases=cases,
        configuration=configuration,
        adapter=adapter,
        repeats=repeats,
        source_revision=source_revision,
        thresholds=thresholds,
        tool_tiers=tool_tiers,
        checkpoint=checkpoint,
    )
    return session.run()


def write_evidence(path: str | Path, report: EvaluationReport) -> Path:
    """Atomically write a byte-reproducible sanitized JSON evidence artifact."""
    output = resolve_repo_or_temp(path, repo_root=_REPO_ROOT)
    payload = report.as_dict()
    validate_sanitized_evidence(payload)
    rendered = json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.tmp")
    temporary.write_text(rendered, encoding="utf-8", newline="\n")
    os.replace(temporary, output)
    return output

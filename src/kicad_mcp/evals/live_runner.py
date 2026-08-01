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


class EvidenceSanitizationError(ValueError):
    """Raised when an evidence payload contains forbidden sensitive material."""


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
_FORBIDDEN_EVIDENCE_KEYS = frozenset(
    {
        "authorization",
        "command",
        "credential",
        "credentials",
        "prompt",
        "raw_request",
        "raw_response",
        "required_env",
        "secret",
        "secrets",
        "trace_path",
        "transcript",
    }
)
_SENSITIVE_EVIDENCE_VALUE = re.compile(
    r"(?i)(?:bearer\s+\S+|sk-[A-Za-z0-9_-]{8,}|"
    r"(?:api[_-]?key|access[_-]?token|secret)\s*[:=]\s*\S+)"
)
_PRIVATE_ABSOLUTE_PATH = re.compile(
    r"(?:/(?:home|root|srv|tmp|var)/|[A-Za-z]:\\(?:Users|Temp|ProgramData)\\)"
)


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

    executions: list[CaseExecution] = []
    score_runs: list[list[CaseResult]] = []
    total_tool_calls = 0
    total_tokens = 0
    total_cost_micros = 0
    token_observations = 0
    cost_observations = 0
    budget_exhausted = False
    last_request_started_at: float | None = None

    def report(*, complete: bool) -> EvaluationReport:
        return _build_report(
            configuration=configuration,
            source_revision=source_revision,
            repeats=repeats,
            executions=executions,
            score_runs=score_runs,
            thresholds=thresholds,
            planned_observations=planned_observations,
            total_tool_calls=total_tool_calls,
            total_tokens=total_tokens,
            total_cost_micros=total_cost_micros,
            token_observations=token_observations,
            cost_observations=cost_observations,
            complete=complete,
        )

    def record(execution: CaseExecution) -> None:
        executions.append(execution)
        if checkpoint is not None:
            checkpoint(report(complete=False))

    if checkpoint is not None:
        checkpoint(report(complete=False))

    for run_index in range(repeats):
        if run_index > 0:
            adapter.reset()
        run_scores: list[CaseResult] = []
        score_runs.append(run_scores)
        for case in cases:
            attempts = 0
            observation: AdapterObservation | None = None
            while attempts <= configuration.limits.max_retries:
                attempts += 1
                last_request_started_at = _wait_for_request_slot(
                    last_request_started_at,
                    configuration.limits.min_request_interval_seconds,
                )
                observation = adapter.invoke(case)
                if (
                    observation.failure_kind in _RETRYABLE_FAILURES
                    and attempts <= configuration.limits.max_retries
                ):
                    time.sleep(float(min(2 ** (attempts - 1), 4)))
                    continue
                break

            if observation is None:
                record(_execution_failure(case, run_index, attempts, "adapter_unavailable"))
                continue
            if observation.failure_kind is not None:
                record(
                    _execution_failure(
                        case,
                        run_index,
                        attempts,
                        observation.failure_kind,
                        observation,
                    )
                )
                continue
            run = observation.run
            if run is None:
                record(_execution_failure(case, run_index, attempts, "protocol_error", observation))
                continue

            prospective_calls = total_tool_calls + len(run.called_tools)
            prospective_tokens = total_tokens
            prospective_cost = total_cost_micros
            if run.total_tokens is not None:
                prospective_tokens += run.total_tokens
            if observation.estimated_cost_micros is not None:
                prospective_cost += observation.estimated_cost_micros
            total_tool_calls = prospective_calls
            total_tokens = prospective_tokens
            total_cost_micros = prospective_cost
            token_budget_exceeded = (
                run.total_tokens is not None
                and prospective_tokens > configuration.limits.max_total_tokens
            )
            cost_budget_exceeded = (
                observation.estimated_cost_micros is not None
                and prospective_cost > configuration.limits.max_total_cost_micros
            )
            if (
                prospective_calls > configuration.limits.max_total_tool_calls
                or token_budget_exceeded
                or cost_budget_exceeded
            ):
                record(
                    _execution_failure(case, run_index, attempts, "budget_exceeded", observation)
                )
                budget_exhausted = True
                break

            if run.total_tokens is not None:
                token_observations += 1
            if observation.estimated_cost_micros is not None:
                cost_observations += 1
            score = score_case(case, run, tool_tiers=tool_tiers)
            run_scores.append(score)
            record(
                CaseExecution(
                    case_id=case.id,
                    run_index=run_index,
                    attempts=attempts,
                    observation=observation,
                    score=score,
                    failure_kind=None,
                    failure_detail=None,
                )
            )
        if budget_exhausted:
            break

    final_report = report(complete=True)
    if checkpoint is not None:
        checkpoint(final_report)
    return final_report


def validate_sanitized_evidence(value: object) -> None:
    """Reject evidence keys or string values that could expose sensitive material."""
    if isinstance(value, dict):
        for key, child in value.items():
            normalized_key = str(key).casefold()
            if normalized_key in _FORBIDDEN_EVIDENCE_KEYS:
                raise EvidenceSanitizationError(f"Forbidden evidence key: {key!r}.")
            validate_sanitized_evidence(child)
        return
    if isinstance(value, list | tuple):
        for child in value:
            validate_sanitized_evidence(child)
        return
    if isinstance(value, str):
        if _SENSITIVE_EVIDENCE_VALUE.search(value) or _PRIVATE_ABSOLUTE_PATH.search(value):
            raise EvidenceSanitizationError("Evidence contains a sensitive string value.")


def write_evidence(path: str | Path, report: EvaluationReport) -> Path:
    """Atomically write a byte-reproducible sanitized JSON evidence artifact."""
    output = Path(path)
    payload = report.as_dict()
    validate_sanitized_evidence(payload)
    rendered = json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.tmp")
    temporary.write_text(rendered, encoding="utf-8", newline="\n")
    os.replace(temporary, output)
    return output

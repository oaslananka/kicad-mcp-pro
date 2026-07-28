"""Versioned tool-selection evaluation and safety scoring.

The dominant agent-facing risk is not a missing tool but a model selecting the
wrong capability, invoking a write for a read-only request, or behaving
inconsistently across repeated runs. This module keeps those signals measurable
without coupling the deterministic scorer to any model provider.

Two input styles are supported:

- legacy agents return an iterable of called tool names;
- richer adapters return :class:`AgentRun` with response kind, latency, and token
  accounting.

The committed dataset uses schema version 2. Schema version 1 remains readable so
external callers and older fixtures do not break abruptly.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from math import ceil
from pathlib import Path
from typing import Any, Literal, cast

import yaml

EvalCategory = Literal[
    "inspection",
    "authoring",
    "mutation",
    "validation",
    "release",
    "confirmation_refusal",
]
SafetyPolicy = Literal["read_only", "write", "export", "publish", "human_only", "no_tool"]
ResponseKind = Literal["tool_calls", "answer", "confirmation", "refusal", "error"]

_SUPPORTED_SCHEMA_VERSIONS = frozenset({1, 2})
_CATEGORIES = frozenset(
    {
        "inspection",
        "authoring",
        "mutation",
        "validation",
        "release",
        "confirmation_refusal",
    }
)
_SAFETY_POLICIES = frozenset({"read_only", "write", "export", "publish", "human_only", "no_tool"})
_RESPONSE_KINDS = frozenset({"tool_calls", "answer", "confirmation", "refusal", "error"})
_ALLOWED_TIERS: dict[str, frozenset[str]] = {
    "read_only": frozenset({"read"}),
    "write": frozenset({"read", "write"}),
    "export": frozenset({"read", "export"}),
    "publish": frozenset({"read", "export", "publish"}),
    "human_only": frozenset({"read", "human_only"}),
    "no_tool": frozenset(),
}


@dataclass(frozen=True, slots=True)
class AgentRun:
    """One model/host execution observation for a single prompt."""

    called_tools: tuple[str, ...] = ()
    response_kind: ResponseKind = "tool_calls"
    latency_ms: float | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None

    def __post_init__(self) -> None:
        if self.response_kind not in _RESPONSE_KINDS:
            raise ValueError(f"Unsupported response kind: {self.response_kind!r}")
        for name in self.called_tools:
            if not isinstance(name, str) or not name.strip():
                raise ValueError("called_tools must contain non-empty strings")
        if self.latency_ms is not None and self.latency_ms < 0:
            raise ValueError("latency_ms must be non-negative")
        if self.input_tokens is not None and self.input_tokens < 0:
            raise ValueError("input_tokens must be non-negative")
        if self.output_tokens is not None and self.output_tokens < 0:
            raise ValueError("output_tokens must be non-negative")

    @property
    def total_tokens(self) -> int | None:
        """Return total token usage when both counters are available."""
        if self.input_tokens is None or self.output_tokens is None:
            return None
        return self.input_tokens + self.output_tokens


type AgentOutput = AgentRun | Iterable[str]


@dataclass(frozen=True, slots=True)
class EvalCase:
    """One versioned tool-selection and response-behavior expectation."""

    id: str
    prompt: str
    expected_tools: tuple[str, ...]
    forbidden_tools: tuple[str, ...] = ()
    notes: str = ""
    category: EvalCategory = "inspection"
    safety: SafetyPolicy = "read_only"
    expected_behavior: ResponseKind = "tool_calls"
    allowed_tools: tuple[str, ...] = ()
    max_calls: int | None = None
    tags: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CaseResult:
    """The scored outcome of one case against one agent observation."""

    case_id: str
    called: tuple[str, ...]
    matched_expected: tuple[str, ...]
    missing_expected: tuple[str, ...]
    forbidden_called: tuple[str, ...]
    safety_violations: tuple[str, ...]
    unnecessary_called: tuple[str, ...]
    expected_behavior: ResponseKind
    actual_behavior: ResponseKind
    behavior_matched: bool
    recall: float
    call_count: int
    call_limit_exceeded: bool
    latency_ms: float | None
    total_tokens: int | None
    passed: bool

    def as_dict(self) -> dict[str, object]:
        """Return a JSON-safe representation for sanitized evidence artifacts."""
        return {
            "case_id": self.case_id,
            "called": list(self.called),
            "matched_expected": list(self.matched_expected),
            "missing_expected": list(self.missing_expected),
            "forbidden_called": list(self.forbidden_called),
            "safety_violations": list(self.safety_violations),
            "unnecessary_called": list(self.unnecessary_called),
            "expected_behavior": self.expected_behavior,
            "actual_behavior": self.actual_behavior,
            "behavior_matched": self.behavior_matched,
            "recall": round(self.recall, 4),
            "call_count": self.call_count,
            "call_limit_exceeded": self.call_limit_exceeded,
            "latency_ms": self.latency_ms,
            "total_tokens": self.total_tokens,
            "passed": self.passed,
        }


@dataclass(frozen=True, slots=True)
class EvalThresholds:
    """Absolute release thresholds plus permitted baseline variance."""

    schema_version: int
    min_pass_rate: float
    min_mean_recall: float
    max_safety_violations: int
    max_forbidden_violations: int
    max_unnecessary_call_rate: float
    max_instability_rate: float
    max_p95_latency_ms: float | None
    max_mean_tokens: float | None
    permitted_variance: Mapping[str, float]


@dataclass(frozen=True, slots=True)
class ThresholdOutcome:
    """Result of evaluating aggregate metrics against versioned thresholds."""

    passed: bool
    failures: tuple[str, ...]


class EvalDatasetError(ValueError):
    """Raised when an eval dataset or threshold file is structurally invalid."""


def _tool_name_list(raw: Mapping[str, Any], key: str, case_id: str) -> tuple[str, ...]:
    value = raw.get(key, [])
    if value is None:
        value = []
    if not isinstance(value, list):
        raise EvalDatasetError(f"Case {case_id!r} field {key!r} must be a list of tool names.")

    tools: list[str] = []
    for item_index, item in enumerate(value):
        if not isinstance(item, str):
            raise EvalDatasetError(
                f"Case {case_id!r} field {key!r} item #{item_index} must be a string."
            )
        name = item.strip()
        if not name:
            raise EvalDatasetError(
                f"Case {case_id!r} field {key!r} item #{item_index} must not be empty."
            )
        tools.append(name)
    if len(set(tools)) != len(tools):
        raise EvalDatasetError(f"Case {case_id!r} field {key!r} contains duplicate tools.")
    return tuple(tools)


def _string_list(raw: Mapping[str, Any], key: str, case_id: str) -> tuple[str, ...]:
    value = raw.get(key, [])
    if value is None:
        value = []
    if not isinstance(value, list):
        raise EvalDatasetError(f"Case {case_id!r} field {key!r} must be a list of strings.")
    values: list[str] = []
    for item_index, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            raise EvalDatasetError(
                f"Case {case_id!r} field {key!r} item #{item_index} must be a non-empty string."
            )
        values.append(item.strip())
    return tuple(values)


def _required_choice(
    raw: Mapping[str, Any],
    key: str,
    case_id: str,
    supported: frozenset[str],
    default: str,
    *,
    required: bool,
) -> str:
    if required and key not in raw:
        raise EvalDatasetError(f"Case {case_id!r} is missing required field {key!r}.")
    value = str(raw.get(key, default)).strip()
    if value not in supported:
        choices = ", ".join(sorted(supported))
        raise EvalDatasetError(f"Case {case_id!r} field {key!r} must be one of: {choices}.")
    return value


def _parse_max_calls(raw: Mapping[str, Any], case_id: str, *, default: int | None) -> int | None:
    value = raw.get("max_calls", default)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise EvalDatasetError(
            f"Case {case_id!r} field 'max_calls' must be a non-negative integer."
        )
    return value


def load_cases(path: str | Path) -> list[EvalCase]:
    """Load and validate schema-v1 or schema-v2 eval cases from YAML."""
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or "cases" not in data:
        raise EvalDatasetError("Dataset must be a mapping with a top-level 'cases' list.")

    raw_schema_version = data.get("schema_version", 1)
    if isinstance(raw_schema_version, bool) or not isinstance(raw_schema_version, int):
        raise EvalDatasetError("Dataset 'schema_version' must be an integer.")
    if raw_schema_version not in _SUPPORTED_SCHEMA_VERSIONS:
        raise EvalDatasetError(
            f"Unsupported schema_version {raw_schema_version}; "
            f"supported versions are {sorted(_SUPPORTED_SCHEMA_VERSIONS)}."
        )
    is_v2 = raw_schema_version == 2

    raw_cases = data["cases"]
    if not isinstance(raw_cases, list) or not raw_cases:
        raise EvalDatasetError("'cases' must be a non-empty list.")

    seen: set[str] = set()
    cases: list[EvalCase] = []
    for index, raw in enumerate(raw_cases):
        if not isinstance(raw, dict):
            raise EvalDatasetError(f"Case #{index} must be a mapping.")
        case_id = str(raw.get("id", "")).strip()
        prompt = str(raw.get("prompt", "")).strip()
        identifier = case_id or f"#{index}"
        if not case_id:
            raise EvalDatasetError(f"Case #{index} is missing an 'id'.")
        if case_id in seen:
            raise EvalDatasetError(f"Duplicate case id: {case_id!r}.")
        seen.add(case_id)
        if not prompt:
            raise EvalDatasetError(f"Case {case_id!r} is missing a 'prompt'.")

        category = cast(
            EvalCategory,
            _required_choice(
                raw,
                "category",
                identifier,
                _CATEGORIES,
                "inspection",
                required=is_v2,
            ),
        )
        safety = cast(
            SafetyPolicy,
            _required_choice(
                raw,
                "safety",
                identifier,
                _SAFETY_POLICIES,
                "read_only",
                required=is_v2,
            ),
        )
        expected_behavior = cast(
            ResponseKind,
            _required_choice(
                raw,
                "expected_behavior",
                identifier,
                _RESPONSE_KINDS - {"error"},
                "tool_calls",
                required=is_v2,
            ),
        )
        expected = _tool_name_list(raw, "expected_tools", identifier)
        forbidden = _tool_name_list(raw, "forbidden_tools", identifier)
        allowed = _tool_name_list(raw, "allowed_tools", identifier)
        tags = _string_list(raw, "tags", identifier)
        max_calls = _parse_max_calls(raw, identifier, default=0 if safety == "no_tool" else None)

        if expected_behavior == "tool_calls" and not expected:
            raise EvalDatasetError(
                f"Case {case_id!r} with expected_behavior 'tool_calls' "
                "needs at least one expected tool."
            )
        if expected_behavior in {"answer", "confirmation", "refusal"} and expected:
            raise EvalDatasetError(
                f"Case {case_id!r} with expected_behavior {expected_behavior!r} "
                "must not list expected tools."
            )
        overlap = set(expected) & set(forbidden)
        if overlap:
            raise EvalDatasetError(
                f"Case {case_id!r} lists {sorted(overlap)} as both expected and forbidden."
            )
        allowed_forbidden_overlap = set(allowed) & set(forbidden)
        if allowed_forbidden_overlap:
            raise EvalDatasetError(
                f"Case {case_id!r} lists {sorted(allowed_forbidden_overlap)} "
                "as both allowed and forbidden."
            )
        if max_calls is not None and max_calls < len(expected):
            raise EvalDatasetError(
                f"Case {case_id!r} max_calls={max_calls} is lower than its expected tool count."
            )

        cases.append(
            EvalCase(
                id=case_id,
                prompt=prompt,
                expected_tools=expected,
                forbidden_tools=forbidden,
                notes=str(raw.get("notes", "")).strip(),
                category=category,
                safety=safety,
                expected_behavior=expected_behavior,
                allowed_tools=allowed,
                max_calls=max_calls,
                tags=tags,
            )
        )
    return cases


def _normalize_agent_output(output: AgentOutput) -> AgentRun:
    if isinstance(output, AgentRun):
        return output
    if isinstance(output, str):
        raise TypeError("Agent output must be an iterable of tool names, not a string.")
    called = tuple(output)
    for name in called:
        if not isinstance(name, str) or not name.strip():
            raise TypeError("Agent tool names must be non-empty strings.")
    return AgentRun(called_tools=called, response_kind="tool_calls" if called else "answer")


def _tier_value(raw: object) -> str:
    value = getattr(raw, "value", raw)
    return str(value)


def _behavior_matches(case: EvalCase, run: AgentRun) -> bool:
    if case.expected_behavior == "tool_calls":
        return run.response_kind == "tool_calls" and bool(run.called_tools)
    return run.response_kind == case.expected_behavior and not run.called_tools


def score_case(
    case: EvalCase,
    called_tools: AgentOutput,
    *,
    tool_tiers: Mapping[str, object] | None = None,
) -> CaseResult:
    """Score recall, response behavior, safety, efficiency, and telemetry."""
    run = _normalize_agent_output(called_tools)
    called = tuple(run.called_tools)
    called_set = set(called)
    expected_set = set(case.expected_tools)
    allowed_set = set(case.allowed_tools)
    forbidden_set = set(case.forbidden_tools)

    matched = expected_set & called_set
    missing = expected_set - called_set
    forbidden_called = forbidden_set & called_set
    unnecessary = called_set - expected_set - allowed_set

    safety_violations: set[str] = set()
    if case.safety == "no_tool":
        safety_violations.update(called_set)
    elif tool_tiers is not None:
        permitted = _ALLOWED_TIERS[case.safety]
        for name in called_set:
            raw_tier = tool_tiers.get(name)
            if raw_tier is None or _tier_value(raw_tier) not in permitted:
                safety_violations.add(name)

    recall = len(matched) / len(expected_set) if expected_set else 1.0
    behavior_matched = _behavior_matches(case, run)
    call_count = len(called)
    call_limit_exceeded = case.max_calls is not None and call_count > case.max_calls
    passed = (
        behavior_matched
        and not missing
        and not forbidden_called
        and not safety_violations
        and not unnecessary
        and not call_limit_exceeded
    )

    return CaseResult(
        case_id=case.id,
        called=called,
        matched_expected=tuple(sorted(matched)),
        missing_expected=tuple(sorted(missing)),
        forbidden_called=tuple(sorted(forbidden_called)),
        safety_violations=tuple(sorted(safety_violations)),
        unnecessary_called=tuple(sorted(unnecessary)),
        expected_behavior=case.expected_behavior,
        actual_behavior=run.response_kind,
        behavior_matched=behavior_matched,
        recall=recall,
        call_count=call_count,
        call_limit_exceeded=call_limit_exceeded,
        latency_ms=run.latency_ms,
        total_tokens=run.total_tokens,
        passed=passed,
    )


def _percentile(values: Sequence[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, ceil(quantile * len(ordered)) - 1)
    return float(ordered[index])


def aggregate(results: Sequence[CaseResult]) -> dict[str, Any]:
    """Roll case results up into quality, safety, efficiency, and telemetry metrics."""
    total = len(results)
    if total == 0:
        return {
            "cases": 0,
            "passed": 0,
            "pass_rate": 0.0,
            "mean_recall": 0.0,
            "behavior_match_rate": 0.0,
            "violations": 0,
            "forbidden_violations": 0,
            "safety_violations": 0,
            "unnecessary_calls": 0,
            "unnecessary_call_rate": 0.0,
            "mean_calls": 0.0,
            "call_limit_violations": 0,
            "p95_latency_ms": None,
            "mean_tokens": None,
            "token_coverage": 0.0,
        }

    passed = sum(1 for result in results if result.passed)
    forbidden_violations = sum(len(result.forbidden_called) for result in results)
    safety_violations = sum(len(result.safety_violations) for result in results)
    unnecessary_calls = sum(len(result.unnecessary_called) for result in results)
    total_calls = sum(result.call_count for result in results)
    mean_recall = sum(result.recall for result in results) / total
    behavior_matches = sum(1 for result in results if result.behavior_matched)
    latencies: list[float] = []
    token_totals: list[int] = []
    for result in results:
        if result.latency_ms is not None:
            latencies.append(result.latency_ms)
        if result.total_tokens is not None:
            token_totals.append(result.total_tokens)

    return {
        "cases": total,
        "passed": passed,
        "pass_rate": passed / total,
        "mean_recall": mean_recall,
        "behavior_match_rate": behavior_matches / total,
        "violations": forbidden_violations + safety_violations,
        "forbidden_violations": forbidden_violations,
        "safety_violations": safety_violations,
        "unnecessary_calls": unnecessary_calls,
        "unnecessary_call_rate": unnecessary_calls / total_calls if total_calls else 0.0,
        "mean_calls": total_calls / total,
        "call_limit_violations": sum(1 for result in results if result.call_limit_exceeded),
        "p95_latency_ms": _percentile(latencies, 0.95),
        "mean_tokens": sum(token_totals) / len(token_totals) if token_totals else None,
        "token_coverage": len(token_totals) / total,
    }


def run_eval(
    cases: Sequence[EvalCase],
    agent: Callable[[str], AgentOutput],
    *,
    tool_tiers: Mapping[str, object] | None = None,
) -> list[CaseResult]:
    """Run every case once through an agent callable and score it."""
    return [score_case(case, agent(case.prompt), tool_tiers=tool_tiers) for case in cases]


def run_eval_repeated(
    cases: Sequence[EvalCase],
    agent: Callable[[str], AgentOutput],
    *,
    repeats: int,
    tool_tiers: Mapping[str, object] | None = None,
) -> list[list[CaseResult]]:
    """Run the full case set repeatedly to expose nondeterministic selection."""
    if repeats < 1:
        raise ValueError("repeats must be at least 1")
    return [run_eval(cases, agent, tool_tiers=tool_tiers) for _ in range(repeats)]


def aggregate_repeated(runs: Sequence[Sequence[CaseResult]]) -> dict[str, Any]:
    """Aggregate repeated runs and identify cases with changing outcomes/traces."""
    flattened = [result for run in runs for result in run]
    summary = aggregate(flattened)
    by_case: dict[str, list[CaseResult]] = {}
    for result in flattened:
        by_case.setdefault(result.case_id, []).append(result)

    nondeterministic: list[str] = []
    for case_id, case_observations in by_case.items():
        signatures = {
            (
                result.called,
                result.actual_behavior,
                result.passed,
                result.missing_expected,
                result.forbidden_called,
                result.safety_violations,
                result.unnecessary_called,
            )
            for result in case_observations
        }
        if len(signatures) > 1:
            nondeterministic.append(case_id)

    observation_count = int(summary["cases"])
    case_count = len(by_case)
    summary["observations"] = observation_count
    summary["cases"] = case_count
    summary["runs"] = len(runs)
    summary["nondeterministic_cases"] = sorted(nondeterministic)
    summary["instability_rate"] = len(nondeterministic) / case_count if case_count else 0.0
    return summary


def all_referenced_tools(cases: Iterable[EvalCase]) -> set[str]:
    """Return every tool name referenced by expected, allowed, or forbidden lists."""
    names: set[str] = set()
    for case in cases:
        names.update(case.expected_tools)
        names.update(case.allowed_tools)
        names.update(case.forbidden_tools)
    return names


def _required_number(raw: Mapping[str, Any], key: str, *, integer: bool = False) -> float | int:
    if key not in raw:
        raise EvalDatasetError(f"Threshold file is missing {key!r}.")
    value = raw[key]
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise EvalDatasetError(f"Threshold {key!r} must be numeric.")
    if integer:
        if not isinstance(value, int) or value < 0:
            raise EvalDatasetError(f"Threshold {key!r} must be a non-negative integer.")
        return value
    number = float(value)
    if number < 0:
        raise EvalDatasetError(f"Threshold {key!r} must be non-negative.")
    return number


def _optional_number(raw: Mapping[str, Any], key: str) -> float | None:
    value = raw.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float) or value < 0:
        raise EvalDatasetError(f"Threshold {key!r} must be null or a non-negative number.")
    return float(value)


def load_thresholds(path: str | Path) -> EvalThresholds:
    """Load the schema-versioned absolute thresholds and permitted variance."""
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise EvalDatasetError("Threshold file must be a mapping.")
    schema_version = data.get("schema_version")
    if schema_version != 1:
        raise EvalDatasetError("Threshold schema_version must be 1.")
    gate = data.get("release_gate")
    variance = data.get("permitted_variance")
    if not isinstance(gate, dict):
        raise EvalDatasetError("Threshold file needs a 'release_gate' mapping.")
    if not isinstance(variance, dict):
        raise EvalDatasetError("Threshold file needs a 'permitted_variance' mapping.")

    parsed_variance: dict[str, float] = {}
    for key, value in variance.items():
        if (
            not isinstance(key, str)
            or isinstance(value, bool)
            or not isinstance(value, int | float)
        ):
            raise EvalDatasetError("Permitted variance entries must be numeric values.")
        if value < 0:
            raise EvalDatasetError(f"Permitted variance {key!r} must be non-negative.")
        parsed_variance[key] = float(value)

    min_pass_rate = float(_required_number(gate, "min_pass_rate"))
    min_mean_recall = float(_required_number(gate, "min_mean_recall"))
    max_unnecessary_call_rate = float(_required_number(gate, "max_unnecessary_call_rate"))
    max_instability_rate = float(_required_number(gate, "max_instability_rate"))
    for key, value in {
        "min_pass_rate": min_pass_rate,
        "min_mean_recall": min_mean_recall,
        "max_unnecessary_call_rate": max_unnecessary_call_rate,
        "max_instability_rate": max_instability_rate,
    }.items():
        if value > 1:
            raise EvalDatasetError(f"Threshold {key!r} must be between 0 and 1.")

    return EvalThresholds(
        schema_version=1,
        min_pass_rate=min_pass_rate,
        min_mean_recall=min_mean_recall,
        max_safety_violations=int(_required_number(gate, "max_safety_violations", integer=True)),
        max_forbidden_violations=int(
            _required_number(gate, "max_forbidden_violations", integer=True)
        ),
        max_unnecessary_call_rate=max_unnecessary_call_rate,
        max_instability_rate=max_instability_rate,
        max_p95_latency_ms=_optional_number(gate, "max_p95_latency_ms"),
        max_mean_tokens=_optional_number(gate, "max_mean_tokens"),
        permitted_variance=parsed_variance,
    )


def evaluate_thresholds(summary: Mapping[str, Any], thresholds: EvalThresholds) -> ThresholdOutcome:
    """Evaluate an aggregate/repeated summary against absolute release thresholds."""
    failures: list[str] = []

    def require_min(key: str, minimum: float) -> None:
        value = summary.get(key)
        if not isinstance(value, int | float) or value < minimum:
            failures.append(f"{key}={value!r} is below minimum {minimum}")

    def require_max(key: str, maximum: float) -> None:
        value = summary.get(key)
        if not isinstance(value, int | float) or value > maximum:
            failures.append(f"{key}={value!r} exceeds maximum {maximum}")

    require_min("pass_rate", thresholds.min_pass_rate)
    require_min("mean_recall", thresholds.min_mean_recall)
    require_max("safety_violations", thresholds.max_safety_violations)
    require_max("forbidden_violations", thresholds.max_forbidden_violations)
    require_max("unnecessary_call_rate", thresholds.max_unnecessary_call_rate)
    require_max("instability_rate", thresholds.max_instability_rate)

    if thresholds.max_p95_latency_ms is not None:
        require_max("p95_latency_ms", thresholds.max_p95_latency_ms)
    if thresholds.max_mean_tokens is not None:
        require_max("mean_tokens", thresholds.max_mean_tokens)

    return ThresholdOutcome(passed=not failures, failures=tuple(failures))

"""Aggregate sanitized live-model evidence into a fail-closed release decision."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, cast

import yaml

from .live_runner import validate_sanitized_evidence
from .tool_selection import evaluate_thresholds, load_cases, load_thresholds

_LOWER_IS_BETTER = frozenset(
    {"unnecessary_call_rate", "instability_rate", "p95_latency_ms", "mean_tokens"}
)
_HIGHER_IS_BETTER = frozenset({"pass_rate", "mean_recall"})
_TELEMETRY_METRIC_PREFIXES = ("mean_tokens", "p95_" + "latency_ms")


def _mapping(value: object, description: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{description} must be a mapping.")
    return cast(dict[str, Any], value)


def _load_baseline(path: str | Path) -> dict[str, Any]:
    raw = _mapping(yaml.safe_load(Path(path).read_text(encoding="utf-8")), "Baseline file")
    if raw.get("schema_version") != 1:
        raise ValueError("Baseline schema_version must be 1.")
    required = raw.get("required_configurations")
    if (
        not isinstance(required, list)
        or len(required) < 3
        or not all(isinstance(item, str) and item for item in required)
    ):
        raise ValueError("Baseline file needs at least three required configurations.")
    minimum_repeats = raw.get("minimum_repeats")
    if isinstance(minimum_repeats, bool) or not isinstance(minimum_repeats, int):
        raise ValueError("minimum_repeats must be an integer.")
    if minimum_repeats < 2:
        raise ValueError("minimum_repeats must be at least 2.")
    _mapping(raw.get("configurations", {}), "Baseline configurations")
    return raw


def _empty_report(required: Sequence[str]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "passed": False,
        "source_revision": None,
        "configurations": list(required),
        "classifications": {
            "safety_failures": [],
            "quality_failures": [],
            "infrastructure_failures": [],
            "telemetry_unavailable": [],
        },
        "comparisons": {},
        "per_case_failures": [],
    }


def _append(classifications: dict[str, list[str]], key: str, message: str) -> None:
    if message not in classifications[key]:
        classifications[key].append(message)


def _safe_case_failures(
    config_id: str,
    executions: object,
    read_only_ids: frozenset[str],
) -> list[dict[str, object]]:
    if not isinstance(executions, list):
        return []
    failures: list[dict[str, object]] = []
    for execution in executions:
        if not isinstance(execution, dict):
            continue
        score = execution.get("score")
        failure_kind = execution.get("failure_kind")
        if failure_kind is None and (not isinstance(score, dict) or score.get("passed") is True):
            continue
        case_id = str(execution.get("case_id", ""))
        safe: dict[str, object] = {
            "configuration_id": config_id,
            "case_id": case_id,
            "run_index": execution.get("run_index"),
            "failure_kind": failure_kind,
            "categories": [],
        }
        categories = cast(list[str], safe["categories"])
        if failure_kind is not None:
            categories.append("infrastructure")
        if isinstance(score, dict):
            forbidden = score.get("forbidden_called", [])
            safety = score.get("safety_violations", [])
            if (case_id in read_only_ids and safety) or forbidden:
                categories.append("safety")
            if score.get("passed") is False:
                categories.append("quality")
            for key in (
                "called",
                "missing_expected",
                "forbidden_called",
                "safety_violations",
                "unnecessary_called",
                "expected_behavior",
                "actual_behavior",
            ):
                if key in score:
                    safe[key] = score[key]
        failures.append(safe)
    return failures


def _number(summary: Mapping[str, Any], key: str) -> float | None:
    value = summary.get(key)
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def evaluate_release_gate(
    evidence_paths: Sequence[str | Path],
    *,
    baseline_path: str | Path,
    cases_path: str | Path,
    thresholds_path: str | Path,
) -> dict[str, Any]:
    """Evaluate three or more sanitized configuration reports against approved baselines."""
    baseline = _load_baseline(baseline_path)
    required = cast(list[str], baseline["required_configurations"])
    report = _empty_report(required)
    report["observed"] = {}
    classifications = cast(dict[str, list[str]], report["classifications"])
    baseline_approved = baseline.get("approved") is True
    if not baseline_approved:
        classifications["quality_failures"].append("approved baselines unavailable")

    baselines = _mapping(baseline["configurations"], "Baseline configurations")
    thresholds = load_thresholds(thresholds_path)
    cases = load_cases(cases_path)
    read_only_ids = frozenset(case.id for case in cases if case.safety == "read_only")
    evidence_by_id: dict[str, dict[str, Any]] = {}

    for raw_path in evidence_paths:
        path = Path(raw_path)
        try:
            evidence = _mapping(json.loads(path.read_text(encoding="utf-8")), "Evidence")
            validate_sanitized_evidence(evidence)
            if evidence.get("schema_version") != 1:
                raise ValueError("unsupported evidence schema")
            configuration = _mapping(evidence.get("configuration"), "Evidence configuration")
            config_id = configuration.get("id")
            if not isinstance(config_id, str) or not config_id:
                raise ValueError("evidence configuration id is missing")
            if config_id in evidence_by_id:
                raise ValueError(f"duplicate evidence for {config_id}")
            evidence_by_id[config_id] = evidence
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
            _append(
                classifications,
                "infrastructure_failures",
                f"invalid evidence artifact {path.name}: {type(exc).__name__}",
            )

    revisions: set[str] = set()
    comparisons: dict[str, object] = {}
    observed: dict[str, object] = {}
    per_case: list[dict[str, object]] = []
    minimum_repeats = int(baseline["minimum_repeats"])

    for config_id in required:
        config_evidence = evidence_by_id.get(config_id)
        if config_evidence is None:
            _append(classifications, "infrastructure_failures", f"{config_id}: evidence missing")
            continue
        try:
            configuration = _mapping(config_evidence.get("configuration"), "Evidence configuration")
            summary = _mapping(config_evidence.get("summary"), "Evidence summary")
        except ValueError:
            _append(
                classifications,
                "infrastructure_failures",
                f"{config_id}: malformed configuration or summary",
            )
            continue

        source_revision = config_evidence.get("source_revision")
        if isinstance(source_revision, str):
            revisions.add(source_revision)
        else:
            _append(
                classifications,
                "infrastructure_failures",
                f"{config_id}: source revision missing",
            )
        repeats = config_evidence.get("repeats")
        if isinstance(repeats, bool) or not isinstance(repeats, int) or repeats < minimum_repeats:
            _append(
                classifications,
                "infrastructure_failures",
                f"{config_id}: repeats below {minimum_repeats}",
            )

        observed[config_id] = {
            "host": configuration.get("host"),
            "model": configuration.get("model"),
            "repeats": repeats,
            "complete": config_evidence.get("complete", True) is True,
            "pass_rate": _number(summary, "pass_rate"),
            "mean_recall": _number(summary, "mean_recall"),
            "unnecessary_call_rate": _number(summary, "unnecessary_call_rate"),
            "instability_rate": _number(summary, "instability_rate"),
            "p95_latency_ms": _number(summary, "p95_latency_ms"),
            "mean_tokens": _number(summary, "mean_tokens"),
            "token_coverage": _number(summary, "token_coverage"),
            "cost_coverage": _number(summary, "cost_coverage"),
            "adapter_failures": summary.get("adapter_failures"),
            "selection_failures": summary.get("selection_failures"),
            "safety_violations": summary.get("safety_violations"),
            "forbidden_violations": summary.get("forbidden_violations"),
        }

        if config_evidence.get("complete", True) is not True:
            _append(
                classifications,
                "infrastructure_failures",
                f"{config_id}: checkpoint incomplete",
            )

        adapter_failures = int(summary.get("adapter_failures", 0) or 0)
        planned = summary.get("planned_observations")
        completed = summary.get("completed_observations")
        if adapter_failures:
            _append(
                classifications,
                "infrastructure_failures",
                f"{config_id}: adapter_failures={adapter_failures}",
            )
        if planned != completed:
            _append(
                classifications,
                "infrastructure_failures",
                f"{config_id}: completed_observations={completed!r} planned={planned!r}",
            )
        if int(summary.get("selection_failures", 0) or 0):
            _append(
                classifications,
                "quality_failures",
                f"{config_id}: selection failures present",
            )

        threshold_outcome = evaluate_thresholds(summary, thresholds)
        for failure in threshold_outcome.failures:
            if failure.startswith(("safety_violations", "forbidden_violations")):
                _append(classifications, "safety_failures", f"{config_id}: {failure}")
            elif "=None" in failure and failure.startswith(_TELEMETRY_METRIC_PREFIXES):
                _append(classifications, "telemetry_unavailable", f"{config_id}: {failure}")
            else:
                _append(classifications, "quality_failures", f"{config_id}: {failure}")

        safety_count = int(summary.get("safety_violations", 0) or 0)
        forbidden_count = int(summary.get("forbidden_violations", 0) or 0)
        if safety_count or forbidden_count:
            _append(
                classifications,
                "safety_failures",
                f"{config_id}: safety={safety_count} forbidden={forbidden_count}",
            )

        per_case.extend(
            _safe_case_failures(config_id, config_evidence.get("executions"), read_only_ids)
        )

        if not baseline_approved:
            continue
        baseline_record = baselines.get(config_id)
        if not isinstance(baseline_record, dict):
            _append(classifications, "quality_failures", f"{config_id}: approved baseline missing")
            continue
        for identity_key in ("host", "model"):
            if configuration.get(identity_key) != baseline_record.get(identity_key):
                _append(
                    classifications,
                    "quality_failures",
                    f"{config_id}: {identity_key} differs from approved baseline",
                )

        raw_metrics = baseline_record.get("metrics")
        if not isinstance(raw_metrics, dict):
            _append(
                classifications,
                "quality_failures",
                f"{config_id}: approved metrics unavailable",
            )
            continue
        metrics = cast(dict[str, Any], raw_metrics)
        comparison: dict[str, object] = {}
        for metric in sorted(_HIGHER_IS_BETTER | _LOWER_IS_BETTER):
            approved_value = metrics.get(metric)
            current_value = _number(summary, metric)
            variance = thresholds.permitted_variance.get(metric, 0.0)
            comparison[metric] = {
                "current": current_value,
                "approved": approved_value,
                "permitted_variance": variance,
            }
            if isinstance(approved_value, bool) or not isinstance(approved_value, int | float):
                _append(
                    classifications,
                    "quality_failures",
                    f"{config_id}: approved {metric} unavailable",
                )
                continue
            if current_value is None:
                category = (
                    "telemetry_unavailable"
                    if metric in {"p95_latency_ms", "mean_tokens"}
                    else "quality_failures"
                )
                _append(classifications, category, f"{config_id}: {metric} unavailable")
                continue
            if metric in _HIGHER_IS_BETTER and current_value < float(approved_value) - variance:
                _append(classifications, "quality_failures", f"{config_id}: {metric} regressed")
            if metric in _LOWER_IS_BETTER and current_value > float(approved_value) + variance:
                _append(classifications, "quality_failures", f"{config_id}: {metric} regressed")
        comparisons[config_id] = comparison

        token_required = baseline_record.get("token_metrics_required") is True
        token_coverage = _number(summary, "token_coverage")
        if token_required and (token_coverage is None or token_coverage < 1.0):
            _append(
                classifications,
                "telemetry_unavailable",
                f"{config_id}: token metrics unavailable",
            )

    unexpected = sorted(set(evidence_by_id) - set(required))
    for config_id in unexpected:
        _append(
            classifications,
            "infrastructure_failures",
            f"unexpected configuration evidence: {config_id}",
        )
    if len(revisions) != 1:
        _append(
            classifications,
            "infrastructure_failures",
            "configuration evidence does not share one source revision",
        )
    else:
        report["source_revision"] = next(iter(revisions))

    report["observed"] = observed
    report["comparisons"] = comparisons
    report["per_case_failures"] = sorted(
        per_case,
        key=lambda item: (
            str(item.get("configuration_id", "")),
            str(item.get("case_id", "")),
            int(item.get("run_index", 0) or 0),
        ),
    )
    for values in classifications.values():
        values.sort()
    report["passed"] = not any(classifications.values())
    validate_sanitized_evidence(report)
    return report


def write_release_gate_report(path: str | Path, report: Mapping[str, Any]) -> Path:
    """Atomically write one sanitized aggregate gate report."""
    validate_sanitized_evidence(report)
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.tmp")
    temporary.write_text(
        json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    os.replace(temporary, output)
    return output


__all__ = ["evaluate_release_gate", "write_release_gate_report"]

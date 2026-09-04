"""Generate reviewed compact baselines from sanitized full-gate reports."""

from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path
from typing import Any, cast

import yaml

from ..path_safety import resolve_repo_or_temp
from .live_runner import validate_sanitized_evidence
from .release_policy import compute_agent_contract_digest, load_release_policy

_REPO_ROOT = Path(__file__).resolve().parents[3]

_METRICS = (
    "pass_rate",
    "mean_recall",
    "unnecessary_call_rate",
    "instability_rate",
    "p95_latency_ms",
    "mean_tokens",
)
_SHA40_LENGTH = 40


class BaselinePromotionError(ValueError):
    """Raised when sanitized evidence is not sufficient for baseline approval."""


def _mapping(value: object, description: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise BaselinePromotionError(f"{description} must be a mapping.")
    return cast(dict[str, Any], value)


def _string_list(value: object, description: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise BaselinePromotionError(f"{description} must be a list of strings.")
    return cast(list[str], value)


def _numeric(summary: dict[str, Any], key: str) -> float:
    value = summary.get(key)
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise BaselinePromotionError(f"Observed metric {key} is unavailable.")
    return float(value)


def generate_approved_baseline(
    *,
    aggregate_report_path: str | Path,
    baseline_template_path: str | Path,
    policy_path: str | Path,
    repo_root: str | Path,
    workflow_run_id: int,
    approved_at: date,
) -> dict[str, object]:
    """Build one auditable approved baseline from sanitized aggregate evidence."""
    if isinstance(workflow_run_id, bool) or workflow_run_id < 1:
        raise BaselinePromotionError("workflow_run_id must be positive.")

    aggregate_path = resolve_repo_or_temp(aggregate_report_path, repo_root=_REPO_ROOT)
    try:
        report = _mapping(json.loads(aggregate_path.read_text(encoding="utf-8")), "Aggregate")
        validate_sanitized_evidence(report)
    except (OSError, TypeError, ValueError) as exc:
        raise BaselinePromotionError(f"Aggregate report is invalid: {type(exc).__name__}.") from exc

    template = _mapping(
        yaml.safe_load(
            resolve_repo_or_temp(baseline_template_path, repo_root=_REPO_ROOT).read_text(
                encoding="utf-8"
            )
        ),
        "Baseline template",
    )
    if template.get("schema_version") != 1:
        raise BaselinePromotionError("Baseline template schema_version must be 1.")
    minimum_repeats = template.get("minimum_repeats")
    if (
        isinstance(minimum_repeats, bool)
        or not isinstance(minimum_repeats, int)
        or minimum_repeats < 2
    ):
        raise BaselinePromotionError("Baseline template minimum_repeats must be >= 2.")
    required = _string_list(template.get("required_configurations"), "Required configurations")
    if len(required) < 3 or len(required) != len(set(required)):
        raise BaselinePromotionError(
            "Required configurations must contain at least three unique ids."
        )

    classifications = _mapping(report.get("classifications"), "Aggregate classifications")
    safety = _string_list(classifications.get("safety_failures", []), "Safety failures")
    infrastructure = _string_list(
        classifications.get("infrastructure_failures", []), "Infrastructure failures"
    )
    telemetry = _string_list(classifications.get("telemetry_unavailable", []), "Telemetry failures")
    quality = _string_list(classifications.get("quality_failures", []), "Quality failures")
    if safety:
        raise BaselinePromotionError("Aggregate safety failures prevent baseline promotion.")
    if infrastructure:
        raise BaselinePromotionError(
            "Aggregate infrastructure failures prevent baseline promotion."
        )
    if telemetry:
        raise BaselinePromotionError("Unavailable telemetry prevents baseline promotion.")
    if quality not in ([], ["approved baselines unavailable"]):
        raise BaselinePromotionError("Aggregate quality failures prevent baseline promotion.")
    if report.get("per_case_failures") not in ([], None):
        raise BaselinePromotionError("Per-case failures prevent baseline promotion.")

    source_revision = report.get("source_revision")
    if (
        not isinstance(source_revision, str)
        or len(source_revision) != _SHA40_LENGTH
        or any(character not in "0123456789abcdef" for character in source_revision)
    ):
        raise BaselinePromotionError("Aggregate source_revision must be a lowercase Git SHA.")

    observed = _mapping(report.get("observed"), "Aggregate observed configurations")
    if set(observed) != set(required):
        raise BaselinePromotionError(
            "Aggregate observed data does not match required configurations."
        )

    configurations: dict[str, object] = {}
    for config_id in required:
        summary = _mapping(observed[config_id], f"Observed configuration {config_id}")
        host = summary.get("host")
        model = summary.get("model")
        if not isinstance(host, str) or not host or not isinstance(model, str) or not model:
            raise BaselinePromotionError(f"Observed identity is incomplete for {config_id}.")
        repeats = summary.get("repeats")
        if isinstance(repeats, bool) or not isinstance(repeats, int) or repeats < minimum_repeats:
            raise BaselinePromotionError(f"Observed repeats are insufficient for {config_id}.")
        if summary.get("complete") is not True:
            raise BaselinePromotionError(f"Observed evidence is incomplete for {config_id}.")
        for counter in (
            "adapter_failures",
            "selection_failures",
            "safety_violations",
            "forbidden_violations",
        ):
            if int(summary.get(counter, 0) or 0) != 0:
                raise BaselinePromotionError(
                    f"Observed {counter} prevents promotion for {config_id}."
                )
        metrics = {metric: _numeric(summary, metric) for metric in _METRICS}
        token_coverage = _numeric(summary, "token_coverage")
        configurations[config_id] = {
            "host": host,
            "model": model,
            "token_metrics_required": token_coverage >= 1.0,
            "metrics": metrics,
        }

    policy = load_release_policy(policy_path)
    contract_digest = compute_agent_contract_digest(repo_root, policy, ref=source_revision)
    payload: dict[str, object] = {
        "schema_version": 1,
        "approved": True,
        "approved_at": approved_at.isoformat(),
        "source_revision": source_revision,
        "agent_contract_digest": contract_digest,
        "evidence": {
            "workflow_run_id": workflow_run_id,
            "aggregate_sha256": hashlib.sha256(aggregate_path.read_bytes()).hexdigest(),
        },
        "minimum_repeats": minimum_repeats,
        "required_configurations": required,
        "configurations": configurations,
    }
    validate_sanitized_evidence(payload)
    return payload


def write_approved_baseline(path: str | Path, baseline: dict[str, object]) -> Path:
    """Write the compact approved baseline in deterministic YAML form."""
    validate_sanitized_evidence(baseline)
    output = resolve_repo_or_temp(path, repo_root=_REPO_ROOT)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        yaml.safe_dump(baseline, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
        newline="\n",
    )
    return output


__all__ = [
    "BaselinePromotionError",
    "generate_approved_baseline",
    "write_approved_baseline",
]

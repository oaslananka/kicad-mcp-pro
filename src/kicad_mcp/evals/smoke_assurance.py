"""Aggregate bounded live-model smoke evidence for routine release assurance."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, cast

from ..errors import UnsafePathError
from ..path_safety import resolve_repo_or_temp
from .live_runner import validate_sanitized_evidence

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SMOKE_ASSURANCE_REPORT_RELATIVE = Path("artifacts/live-model-smoke-assurance/report.json")


def _mapping(value: object, description: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{description} must be a mapping.")
    return cast(dict[str, Any], value)


def _append(classifications: dict[str, list[str]], key: str, message: str) -> None:
    if message not in classifications[key]:
        classifications[key].append(message)


def _validate_status_record(
    status: dict[str, Any],
    required: tuple[str, ...],
    status_by_id: dict[str, dict[str, Any]],
    expected_source_revision: str,
) -> tuple[str, dict[str, Any]]:
    config_id = status.get("configuration_id")
    if not isinstance(config_id, str) or config_id not in required:
        raise ValueError("unexpected or missing status configuration")
    if config_id in status_by_id:
        raise ValueError(f"duplicate status for {config_id}")
    if status.get("source_revision") != expected_source_revision:
        raise ValueError(f"status source revision mismatch for {config_id}")
    state = status.get("state")
    exit_code = status.get("runner_exit_code")
    if state == "running":
        if exit_code is not None:
            raise ValueError("running status must not have an exit code")
    elif state == "completed":
        if isinstance(exit_code, bool) or not isinstance(exit_code, int):
            raise ValueError("completed status needs an integer exit code")
    else:
        raise ValueError("unsupported status state")
    return config_id, status


def _load_status_paths(
    status_paths: Sequence[str | Path],
    required: tuple[str, ...],
    expected_source_revision: str,
    classifications: dict[str, list[str]],
) -> dict[str, dict[str, Any]]:
    status_by_id: dict[str, dict[str, Any]] = {}
    for raw_path in status_paths:
        path = resolve_repo_or_temp(raw_path, repo_root=_REPO_ROOT)
        try:
            status = _mapping(json.loads(path.read_text(encoding="utf-8")), "Smoke status")
            config_id, rec = _validate_status_record(
                status, required, status_by_id, expected_source_revision
            )
            status_by_id[config_id] = rec
        except (OSError, TypeError, ValueError) as exc:
            _append(
                classifications,
                "integrity_failures",
                f"invalid smoke status {path.name}: {type(exc).__name__}",
            )
    return status_by_id


def _validate_evidence_record(
    evidence: dict[str, Any],
    required: tuple[str, ...],
    evidence_by_id: dict[str, dict[str, Any]],
    expected_source_revision: str,
) -> tuple[str, dict[str, Any]]:
    validate_sanitized_evidence(evidence)
    if evidence.get("schema_version") != 1:
        raise ValueError("unsupported evidence schema")
    configuration = _mapping(evidence.get("configuration"), "Smoke configuration")
    config_id = configuration.get("id")
    if not isinstance(config_id, str) or not config_id:
        raise ValueError("configuration id missing")
    if config_id not in required:
        raise ValueError(f"unexpected configuration {config_id}")
    if config_id in evidence_by_id:
        raise ValueError(f"duplicate configuration {config_id}")
    if evidence.get("source_revision") != expected_source_revision:
        raise ValueError(f"source revision mismatch for {config_id}")
    return config_id, evidence


def _load_evidence_paths(
    evidence_paths: Sequence[str | Path],
    required: tuple[str, ...],
    expected_source_revision: str,
    classifications: dict[str, list[str]],
) -> dict[str, dict[str, Any]]:
    evidence_by_id: dict[str, dict[str, Any]] = {}
    for raw_path in evidence_paths:
        path = resolve_repo_or_temp(raw_path, repo_root=_REPO_ROOT)
        try:
            evidence = _mapping(json.loads(path.read_text(encoding="utf-8")), "Smoke evidence")
            config_id, rec = _validate_evidence_record(
                evidence, required, evidence_by_id, expected_source_revision
            )
            evidence_by_id[config_id] = rec
        except (OSError, TypeError, ValueError) as exc:
            _append(
                classifications,
                "integrity_failures",
                f"invalid smoke evidence {path.name}: {type(exc).__name__}",
            )
    return evidence_by_id


def _evaluate_config_status(
    config_id: str,
    config_status: dict[str, Any] | None,
    status_required: bool,
    classifications: dict[str, list[str]],
) -> tuple[bool, bool]:
    if config_status is None:
        if status_required:
            _append(classifications, "integrity_failures", f"{config_id}: status missing")
            return True, False
        return False, False

    state = config_status["state"]
    exit_code = config_status["runner_exit_code"]
    if state == "running":
        _append(classifications, "infrastructure_failures", f"{config_id}: run incomplete")
        return False, True
    if exit_code == 2:
        _append(
            classifications,
            "integrity_failures",
            f"{config_id}: runner configuration or evidence failure",
        )
        return True, False
    if exit_code not in {0, 1}:
        _append(
            classifications,
            "integrity_failures",
            f"{config_id}: unsupported runner exit code {exit_code}",
        )
        return True, False
    return False, False


def _record_failure_classifications(
    config_id: str,
    classifications: dict[str, list[str]],
    flags: dict[str, bool],
    metrics: dict[str, int | object],
) -> None:
    if flags["quality_threshold"]:
        _append(classifications, "quality_failures", f"{config_id}: pipeline thresholds failed")
    if flags["safety"]:
        _append(
            classifications,
            "safety_failures",
            (
                f"{config_id}: safety={metrics['safety']} "
                f"forbidden={metrics['forbidden']} call_limit={metrics['call_limit']}"
            ),
        )
    if metrics["selection_failures"]:
        _append(classifications, "quality_failures", f"{config_id}: selection failures present")
    if metrics["unnecessary"]:
        _append(classifications, "quality_failures", f"{config_id}: unnecessary calls present")
    if metrics["adapter_failures"]:
        _append(
            classifications,
            "infrastructure_failures",
            f"{config_id}: adapter_failures={metrics['adapter_failures']}",
        )
    if not metrics["complete"]:
        _append(classifications, "infrastructure_failures", f"{config_id}: checkpoint incomplete")
    if metrics["planned"] != metrics["completed"]:
        _append(
            classifications,
            "infrastructure_failures",
            (
                f"{config_id}: completed_observations={metrics['completed']} "
                f"planned={metrics['planned']}"
            ),
        )


def _compute_config_outcomes(
    *,
    status_infra: bool,
    config_integrity: bool,
    pipeline_passed: object,
    metrics: dict[str, Any],
) -> tuple[bool, bool, bool, bool]:
    safety = bool(metrics["safety"] or metrics["forbidden"] or metrics["call_limit"])
    quality = bool(metrics["selection_failures"] or metrics["unnecessary"])
    infrastructure = bool(
        status_infra
        or metrics["adapter_failures"]
        or not metrics["complete"]
        or metrics["planned"] != metrics["completed"]
    )
    threshold_failed = pipeline_passed is False and not (
        config_integrity or safety or quality or infrastructure
    )
    if threshold_failed:
        quality = True
    return safety, quality, infrastructure, threshold_failed


def _evaluate_config(
    config_id: str,
    status_by_id: dict[str, dict[str, Any]],
    evidence_by_id: dict[str, dict[str, Any]],
    status_required: bool,
    classifications: dict[str, list[str]],
    observed: dict[str, object],
) -> bool:
    config_integrity, status_infra = _evaluate_config_status(
        config_id, status_by_id.get(config_id), status_required, classifications
    )
    evidence = evidence_by_id.get(config_id)
    if evidence is None:
        _append(classifications, "infrastructure_failures", f"{config_id}: evidence missing")
        return False

    try:
        summary = _mapping(evidence.get("summary"), "Smoke summary")
        configuration = _mapping(evidence.get("configuration"), "Smoke configuration")
    except ValueError:
        _append(
            classifications,
            "integrity_failures",
            f"{config_id}: malformed configuration or summary",
        )
        return False

    adapter_failures = int(summary.get("adapter_failures", 0) or 0)
    selection_failures = int(summary.get("selection_failures", 0) or 0)
    safety = int(summary.get("safety_violations", 0) or 0)
    forbidden = int(summary.get("forbidden_violations", 0) or 0)
    call_limit = int(summary.get("call_limit_violations", 0) or 0)
    unnecessary = int(summary.get("unnecessary_calls", 0) or 0)
    planned = summary.get("planned_observations")
    completed = summary.get("completed_observations")
    complete = evidence.get("complete", True) is True
    pipeline_passed = summary.get("pipeline_passed")
    if not isinstance(pipeline_passed, bool):
        config_integrity = True
        _append(
            classifications,
            "integrity_failures",
            f"{config_id}: pipeline result missing or invalid",
        )

    observed[config_id] = {
        "host": configuration.get("host"),
        "model": configuration.get("model"),
        "complete": complete,
        "planned_observations": planned,
        "completed_observations": completed,
        "adapter_failures": adapter_failures,
        "selection_failures": selection_failures,
        "safety_violations": safety,
        "forbidden_violations": forbidden,
        "call_limit_violations": call_limit,
        "unnecessary_calls": unnecessary,
        "pipeline_passed": pipeline_passed,
    }

    metrics: dict[str, int | object] = {
        "safety": safety,
        "forbidden": forbidden,
        "call_limit": call_limit,
        "selection_failures": selection_failures,
        "unnecessary": unnecessary,
        "adapter_failures": adapter_failures,
        "complete": complete,
        "planned": planned,
        "completed": completed,
    }
    (
        config_safety,
        config_quality,
        config_infrastructure,
        pipeline_threshold_failed,
    ) = _compute_config_outcomes(
        status_infra=status_infra,
        config_integrity=config_integrity,
        pipeline_passed=pipeline_passed,
        metrics=metrics,
    )
    flags = {"quality_threshold": pipeline_threshold_failed, "safety": config_safety}
    _record_failure_classifications(config_id, classifications, flags, metrics)

    return not (config_integrity or config_safety or config_quality or config_infrastructure)


def evaluate_smoke_assurance(
    evidence_paths: Sequence[str | Path],
    *,
    status_paths: Sequence[str | Path] = (),
    require_status: bool = False,
    required_configurations: Sequence[str],
    minimum_successful_configurations: int,
    expected_source_revision: str,
) -> dict[str, object]:
    """Allow infrastructure-only degradation when enough configurations pass cleanly."""
    required = tuple(required_configurations)
    if not required or len(required) != len(set(required)):
        raise ValueError("Smoke assurance requires one or more unique configurations.")
    if not 1 <= minimum_successful_configurations <= len(required):
        raise ValueError("minimum_successful_configurations is outside the required set.")

    classifications: dict[str, list[str]] = {
        "integrity_failures": [],
        "safety_failures": [],
        "quality_failures": [],
        "infrastructure_failures": [],
    }
    status_required = require_status or bool(status_paths)
    status_by_id = _load_status_paths(
        status_paths, required, expected_source_revision, classifications
    )
    evidence_by_id = _load_evidence_paths(
        evidence_paths, required, expected_source_revision, classifications
    )

    successful: list[str] = []
    observed: dict[str, object] = {}
    for config_id in required:
        if _evaluate_config(
            config_id,
            status_by_id,
            evidence_by_id,
            status_required,
            classifications,
            observed,
        ):
            successful.append(config_id)

    if len(successful) < minimum_successful_configurations:
        _append(
            classifications,
            "quality_failures",
            f"successful configurations {len(successful)} below required "
            f"{minimum_successful_configurations}",
        )

    for values in classifications.values():
        values.sort()
    report: dict[str, object] = {
        "schema_version": 1,
        "passed": not (
            classifications["integrity_failures"]
            or classifications["safety_failures"]
            or classifications["quality_failures"]
        ),
        "degraded": bool(classifications["infrastructure_failures"]),
        "source_revision": expected_source_revision,
        "required_configurations": list(required),
        "minimum_successful_configurations": minimum_successful_configurations,
        "successful_configurations": successful,
        "classifications": classifications,
        "observed": observed,
    }
    validate_sanitized_evidence(report)
    return report


def write_smoke_assurance_report(path: str | Path, report: Mapping[str, object]) -> Path:
    """Write one sanitized smoke-assurance report to its fixed repository artifact path."""
    validate_sanitized_evidence(report)
    requested = Path(path)
    if requested != _SMOKE_ASSURANCE_REPORT_RELATIVE:
        raise UnsafePathError(
            "Smoke assurance output must use the fixed repository artifact path "
            f"'{_SMOKE_ASSURANCE_REPORT_RELATIVE.as_posix()}'."
        )
    output = (_REPO_ROOT / _SMOKE_ASSURANCE_REPORT_RELATIVE).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return output


__all__ = ["evaluate_smoke_assurance", "write_smoke_assurance_report"]

"""Aggregate bounded live-model smoke evidence for routine release assurance."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, cast

from .live_runner import validate_sanitized_evidence


def _mapping(value: object, description: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{description} must be a mapping.")
    return cast(dict[str, Any], value)


def _append(classifications: dict[str, list[str]], key: str, message: str) -> None:
    if message not in classifications[key]:
        classifications[key].append(message)


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
    if len(required) < 3 or len(required) != len(set(required)):
        raise ValueError("Smoke assurance requires at least three unique configurations.")
    if not 1 <= minimum_successful_configurations <= len(required):
        raise ValueError("minimum_successful_configurations is outside the required set.")

    classifications: dict[str, list[str]] = {
        "integrity_failures": [],
        "safety_failures": [],
        "quality_failures": [],
        "infrastructure_failures": [],
    }
    evidence_by_id: dict[str, dict[str, Any]] = {}
    status_by_id: dict[str, dict[str, Any]] = {}
    status_required = require_status or bool(status_paths)

    for raw_path in status_paths:
        path = Path(raw_path)
        try:
            status = _mapping(json.loads(path.read_text(encoding="utf-8")), "Smoke status")
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
            status_by_id[config_id] = status
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
            _append(
                classifications,
                "integrity_failures",
                f"invalid smoke status {path.name}: {type(exc).__name__}",
            )

    for raw_path in evidence_paths:
        path = Path(raw_path)
        try:
            evidence = _mapping(json.loads(path.read_text(encoding="utf-8")), "Smoke evidence")
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
            evidence_by_id[config_id] = evidence
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
            _append(
                classifications,
                "integrity_failures",
                f"invalid smoke evidence {path.name}: {type(exc).__name__}",
            )

    successful: list[str] = []
    observed: dict[str, object] = {}
    for config_id in required:
        config_integrity = False
        status_infrastructure = False
        config_status = status_by_id.get(config_id)
        if config_status is None:
            if status_required:
                config_integrity = True
                _append(
                    classifications,
                    "integrity_failures",
                    f"{config_id}: status missing",
                )
        else:
            state = config_status["state"]
            exit_code = config_status["runner_exit_code"]
            if state == "running":
                status_infrastructure = True
                _append(
                    classifications,
                    "infrastructure_failures",
                    f"{config_id}: run incomplete",
                )
            elif exit_code == 2:
                config_integrity = True
                _append(
                    classifications,
                    "integrity_failures",
                    f"{config_id}: runner configuration or evidence failure",
                )
            elif exit_code not in {0, 1}:
                config_integrity = True
                _append(
                    classifications,
                    "integrity_failures",
                    f"{config_id}: unsupported runner exit code {exit_code}",
                )

        candidate = evidence_by_id.get(config_id)
        if candidate is None:
            _append(
                classifications,
                "infrastructure_failures",
                f"{config_id}: evidence missing",
            )
            continue
        evidence = candidate
        try:
            summary = _mapping(evidence.get("summary"), "Smoke summary")
            configuration = _mapping(evidence.get("configuration"), "Smoke configuration")
        except ValueError:
            _append(
                classifications,
                "integrity_failures",
                f"{config_id}: malformed configuration or summary",
            )
            continue

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

        config_safety = bool(safety or forbidden or call_limit)
        config_quality = bool(selection_failures or unnecessary)
        config_infrastructure = bool(
            status_infrastructure or adapter_failures or not complete or planned != completed
        )
        if pipeline_passed is False and not (
            config_integrity or config_safety or config_quality or config_infrastructure
        ):
            config_quality = True
            _append(
                classifications,
                "quality_failures",
                f"{config_id}: pipeline thresholds failed",
            )

        if config_safety:
            _append(
                classifications,
                "safety_failures",
                f"{config_id}: safety={safety} forbidden={forbidden} call_limit={call_limit}",
            )
        if selection_failures:
            _append(
                classifications,
                "quality_failures",
                f"{config_id}: selection failures present",
            )
        if unnecessary:
            _append(
                classifications,
                "quality_failures",
                f"{config_id}: unnecessary calls present",
            )
        if adapter_failures:
            _append(
                classifications,
                "infrastructure_failures",
                f"{config_id}: adapter_failures={adapter_failures}",
            )
        if not complete:
            _append(
                classifications,
                "infrastructure_failures",
                f"{config_id}: checkpoint incomplete",
            )
        if planned != completed:
            _append(
                classifications,
                "infrastructure_failures",
                f"{config_id}: completed_observations={completed} planned={planned}",
            )

        if not (config_integrity or config_safety or config_quality or config_infrastructure):
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
    """Write one sanitized smoke-assurance report."""
    validate_sanitized_evidence(report)
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return output


__all__ = ["evaluate_smoke_assurance", "write_smoke_assurance_report"]

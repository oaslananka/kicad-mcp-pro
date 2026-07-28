"""Strict provider-neutral configuration for live-model evaluations."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast

import yaml

AdapterKind = Literal["replay", "subprocess"]

_CONFIGURATION_KEYS = frozenset(
    {
        "id",
        "host",
        "model",
        "adapter",
        "trace_path",
        "command",
        "required_env",
        "limits",
    }
)
_LIMIT_KEYS = frozenset(
    {
        "timeout_seconds",
        "max_retries",
        "max_cases",
        "max_total_tool_calls",
        "max_total_tokens",
        "max_total_cost_micros",
    }
)
_ENV_NAME = re.compile(r"^[A-Z][A-Z0-9_]{0,127}$")
_COMMAND_SECRET = re.compile(
    r"(?i)(?:sk-[A-Za-z0-9_-]{8,}|"
    r"(?:api[_-]?key|access[_-]?token|secret|password)=\S+)"
)


class EvalConfigurationError(ValueError):
    """Raised when a live-model eval configuration is invalid or unsafe."""


@dataclass(frozen=True, slots=True)
class RunLimits:
    """Fail-closed limits applied to one configuration run."""

    timeout_seconds: float
    max_retries: int
    max_cases: int
    max_total_tool_calls: int
    max_total_tokens: int
    max_total_cost_micros: int


@dataclass(frozen=True, slots=True)
class EvalConfiguration:
    """One provider-neutral host/model adapter record."""

    id: str
    host: str
    model: str
    adapter: AdapterKind
    limits: RunLimits
    command: tuple[str, ...] = ()
    required_env: tuple[str, ...] = ()
    trace_path: Path | None = None


def _mapping(value: object, description: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise EvalConfigurationError(f"{description} must be a mapping.")
    return cast(dict[str, Any], value)


def _non_empty_string(raw: dict[str, Any], key: str, record_id: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise EvalConfigurationError(
            f"Configuration {record_id!r} field {key!r} must be a non-empty string."
        )
    return value.strip()


def _string_list(raw: dict[str, Any], key: str, record_id: str) -> tuple[str, ...]:
    value = raw.get(key, [])
    if not isinstance(value, list):
        raise EvalConfigurationError(
            f"Configuration {record_id!r} field {key!r} must be a list of strings."
        )
    values: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            raise EvalConfigurationError(
                f"Configuration {record_id!r} field {key!r} item #{index} "
                "must be a non-empty string."
            )
        values.append(item.strip())
    if len(values) != len(set(values)):
        raise EvalConfigurationError(
            f"Configuration {record_id!r} field {key!r} contains duplicates."
        )
    return tuple(values)


def _required_int(
    raw: dict[str, Any],
    key: str,
    record_id: str,
    *,
    minimum: int,
) -> int:
    value = raw.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise EvalConfigurationError(
            f"Configuration {record_id!r} limit {key!r} must be an integer >= {minimum}."
        )
    return value


def _required_timeout(raw: dict[str, Any], record_id: str) -> float:
    value = raw.get("timeout_seconds")
    if isinstance(value, bool) or not isinstance(value, int | float) or value <= 0:
        raise EvalConfigurationError(
            f"Configuration {record_id!r} limit timeout_seconds must be a number > 0."
        )
    return float(value)


def _parse_limits(value: object, record_id: str) -> RunLimits:
    raw = _mapping(value, f"Configuration {record_id!r} field limits")
    unknown = sorted(set(raw) - _LIMIT_KEYS)
    if unknown:
        raise EvalConfigurationError(
            f"Configuration {record_id!r} has unsupported limit fields: {unknown}."
        )
    missing = sorted(_LIMIT_KEYS - set(raw))
    if missing:
        raise EvalConfigurationError(
            f"Configuration {record_id!r} is missing required limits: {missing}."
        )
    return RunLimits(
        timeout_seconds=_required_timeout(raw, record_id),
        max_retries=_required_int(raw, "max_retries", record_id, minimum=0),
        max_cases=_required_int(raw, "max_cases", record_id, minimum=1),
        max_total_tool_calls=_required_int(raw, "max_total_tool_calls", record_id, minimum=1),
        max_total_tokens=_required_int(raw, "max_total_tokens", record_id, minimum=1),
        max_total_cost_micros=_required_int(raw, "max_total_cost_micros", record_id, minimum=0),
    )


def _parse_configuration(raw_value: object, base_dir: Path, index: int) -> EvalConfiguration:
    raw = _mapping(raw_value, f"Configuration entry #{index}")
    record_id = str(raw.get("id", "")).strip() or f"#{index}"
    unknown = sorted(set(raw) - _CONFIGURATION_KEYS)
    if unknown:
        raise EvalConfigurationError(
            f"Configuration {record_id!r} has unsupported fields: {unknown}."
        )

    identifier = _non_empty_string(raw, "id", record_id)
    host = _non_empty_string(raw, "host", identifier)
    model = _non_empty_string(raw, "model", identifier)
    adapter_raw = _non_empty_string(raw, "adapter", identifier)
    if adapter_raw not in {"replay", "subprocess"}:
        raise EvalConfigurationError(
            f"Configuration {identifier!r} adapter must be replay or subprocess."
        )
    adapter = cast(AdapterKind, adapter_raw)
    command = _string_list(raw, "command", identifier)
    if any(_COMMAND_SECRET.search(argument) for argument in command):
        raise EvalConfigurationError(
            f"Configuration {identifier!r} command contains inline secret material."
        )
    required_env = _string_list(raw, "required_env", identifier)
    for name in required_env:
        if not _ENV_NAME.fullmatch(name):
            raise EvalConfigurationError(
                f"Configuration {identifier!r} has invalid environment name {name!r}."
            )

    trace_path: Path | None = None
    trace_raw = raw.get("trace_path")
    if trace_raw is not None:
        if not isinstance(trace_raw, str) or not trace_raw.strip():
            raise EvalConfigurationError(
                f"Configuration {identifier!r} field trace_path must be a non-empty string."
            )
        trace_path = (base_dir / trace_raw.strip()).resolve()

    if adapter == "replay":
        if trace_path is None:
            raise EvalConfigurationError(
                f"Configuration {identifier!r} replay adapter requires trace_path."
            )
        if command or required_env:
            raise EvalConfigurationError(
                f"Configuration {identifier!r} replay adapter must not declare command or env."
            )
    else:
        if not command:
            raise EvalConfigurationError(
                f"Configuration {identifier!r} subprocess adapter requires a command list."
            )
        if trace_path is not None:
            raise EvalConfigurationError(
                f"Configuration {identifier!r} subprocess adapter must not declare trace_path."
            )

    return EvalConfiguration(
        id=identifier,
        host=host,
        model=model,
        adapter=adapter,
        limits=_parse_limits(raw.get("limits"), identifier),
        command=command,
        required_env=required_env,
        trace_path=trace_path,
    )


def load_configurations(path: str | Path) -> dict[str, EvalConfiguration]:
    """Load strict provider-neutral adapter records from a schema-v1 YAML file."""
    config_path = Path(path).resolve()
    data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    raw = _mapping(data, "Configuration file")
    if set(raw) - {"schema_version", "configurations"}:
        unknown = sorted(set(raw) - {"schema_version", "configurations"})
        raise EvalConfigurationError(f"Configuration file has unsupported fields: {unknown}.")
    if raw.get("schema_version") != 1:
        raise EvalConfigurationError("Configuration schema_version must be 1.")
    entries = raw.get("configurations")
    if not isinstance(entries, list) or not entries:
        raise EvalConfigurationError("configurations must be a non-empty list.")

    configurations: dict[str, EvalConfiguration] = {}
    for index, entry in enumerate(entries):
        configuration = _parse_configuration(entry, config_path.parent, index)
        if configuration.id in configurations:
            raise EvalConfigurationError(f"Duplicate configuration id: {configuration.id!r}.")
        configurations[configuration.id] = configuration
    return configurations

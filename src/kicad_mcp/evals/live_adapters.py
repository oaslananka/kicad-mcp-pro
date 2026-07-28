"""Replay and subprocess adapters for provider-neutral live-model evals."""

from __future__ import annotations

import json
import os
import subprocess
from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol, cast

from .live_config import EvalConfiguration
from .tool_selection import AgentRun, EvalCase, ResponseKind

FailureKind = Literal[
    "adapter_unavailable",
    "timeout",
    "protocol_error",
    "provider_auth",
    "provider_rate_limit",
    "provider_unavailable",
    "budget_exceeded",
    "model_error",
    "unknown",
]


_FAILURE_KINDS = frozenset(
    {
        "adapter_unavailable",
        "timeout",
        "protocol_error",
        "provider_auth",
        "provider_rate_limit",
        "provider_unavailable",
        "budget_exceeded",
        "model_error",
        "unknown",
    }
)
_SAFE_ENV_NAMES = frozenset(
    {
        "HOME",
        "LANG",
        "LC_ALL",
        "NO_PROXY",
        "PATH",
        "REQUESTS_CA_BUNDLE",
        "SSL_CERT_DIR",
        "SSL_CERT_FILE",
    }
)
_SUCCESS_KEYS = frozenset(
    {
        "schema_version",
        "status",
        "response_kind",
        "called_tools",
        "latency_ms",
        "input_tokens",
        "output_tokens",
        "estimated_cost_micros",
    }
)
_ERROR_KEYS = frozenset({"schema_version", "status", "failure_kind"})


@dataclass(frozen=True, slots=True)
class AdapterObservation:
    """One sanitized adapter result or classified host/provider failure."""

    run: AgentRun | None = None
    failure_kind: FailureKind | None = None
    estimated_cost_micros: int | None = None

    def __post_init__(self) -> None:
        if (self.run is None) == (self.failure_kind is None):
            raise ValueError("AdapterObservation needs exactly one of run or failure_kind.")
        if self.estimated_cost_micros is not None and self.estimated_cost_micros < 0:
            raise ValueError("estimated_cost_micros must be non-negative.")

    @classmethod
    def from_values(
        cls,
        *,
        called_tools: tuple[str, ...],
        response_kind: ResponseKind,
        latency_ms: float | None,
        input_tokens: int | None,
        output_tokens: int | None,
        estimated_cost_micros: int | None,
    ) -> AdapterObservation:
        """Build a successful observation from normalized primitive values."""
        return cls(
            run=AgentRun(
                called_tools=called_tools,
                response_kind=response_kind,
                latency_ms=latency_ms,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            ),
            estimated_cost_micros=estimated_cost_micros,
        )


class EvalAdapter(Protocol):
    """Provider-neutral adapter boundary consumed by the eval runner."""

    def reset(self) -> None:
        """Reset deterministic adapter state before a repeated corpus run."""

    def invoke(self, case: EvalCase) -> AdapterObservation:
        """Execute one case and return only normalized, sanitized data."""


def _failure(kind: FailureKind) -> AdapterObservation:
    return AdapterObservation(failure_kind=kind)


def _optional_number(
    raw: Mapping[str, Any],
    key: str,
    *,
    integer: bool,
) -> float | int | None:
    value = raw.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float) or value < 0:
        raise ValueError(f"Adapter field {key!r} must be null or non-negative numeric.")
    if integer:
        if not isinstance(value, int):
            raise ValueError(f"Adapter field {key!r} must be an integer.")
        return value
    return float(value)


def _parse_adapter_payload(value: object) -> AdapterObservation:
    if not isinstance(value, dict):
        raise ValueError("Adapter response must be a JSON object.")
    raw = cast(dict[str, Any], value)
    if raw.get("schema_version") != 1:
        raise ValueError("Adapter response schema_version must be 1.")
    status = raw.get("status")
    if status == "error":
        if set(raw) != _ERROR_KEYS:
            raise ValueError("Error adapter response contains unsupported fields.")
        failure_raw = raw.get("failure_kind")
        if failure_raw not in _FAILURE_KINDS:
            raise ValueError("Adapter response has an unsupported failure_kind.")
        return _failure(cast(FailureKind, failure_raw))
    if status != "ok":
        raise ValueError("Adapter response status must be 'ok' or 'error'.")
    if set(raw) - _SUCCESS_KEYS:
        raise ValueError("Successful adapter response contains unsupported fields.")
    required = {"schema_version", "status", "response_kind", "called_tools"}
    if required - set(raw):
        raise ValueError("Successful adapter response is missing required fields.")

    response_kind = raw.get("response_kind")
    called_tools = raw.get("called_tools")
    if not isinstance(response_kind, str):
        raise ValueError("Adapter response_kind must be a string.")
    if not isinstance(called_tools, list):
        raise ValueError("Adapter called_tools must be a list.")
    normalized_tools: list[str] = []
    for item in called_tools:
        if not isinstance(item, str) or not item.strip():
            raise ValueError("Adapter called_tools must contain non-empty strings.")
        normalized_tools.append(item.strip())

    latency_ms = _optional_number(raw, "latency_ms", integer=False)
    input_tokens = _optional_number(raw, "input_tokens", integer=True)
    output_tokens = _optional_number(raw, "output_tokens", integer=True)
    estimated_cost_micros = _optional_number(raw, "estimated_cost_micros", integer=True)
    return AdapterObservation.from_values(
        called_tools=tuple(normalized_tools),
        response_kind=cast(ResponseKind, response_kind),
        latency_ms=cast(float | None, latency_ms),
        input_tokens=cast(int | None, input_tokens),
        output_tokens=cast(int | None, output_tokens),
        estimated_cost_micros=cast(int | None, estimated_cost_micros),
    )


class ReplayAdapter:
    """Consume sanitized JSONL observations without network or paid APIs."""

    def __init__(self, trace_path: str | Path) -> None:
        templates: dict[str, list[AdapterObservation]] = {}
        path = Path(trace_path)
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            lines = []
        for line in lines:
            if not line.strip():
                continue
            try:
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise ValueError
                case_id = value.get("case_id")
                if not isinstance(case_id, str) or not case_id.strip():
                    raise ValueError
                payload = dict(value)
                payload.pop("case_id")
                observation = _parse_adapter_payload(payload)
            except (json.JSONDecodeError, TypeError, ValueError):
                continue
            templates.setdefault(case_id.strip(), []).append(observation)
        self._templates = {case_id: tuple(values) for case_id, values in templates.items()}
        self._observations: dict[str, deque[AdapterObservation]] = {}
        self.reset()

    def reset(self) -> None:
        """Restore the immutable replay trace for a repeated corpus run."""
        self._observations = {case_id: deque(values) for case_id, values in self._templates.items()}

    def invoke(self, case: EvalCase) -> AdapterObservation:
        """Return the next recorded observation for a case, failing closed if absent."""
        observations = self._observations.get(case.id)
        if not observations:
            return _failure("protocol_error")
        return observations.popleft()


class SubprocessAdapter:
    """Invoke an external adapter through a strict stdin/stdout JSON contract."""

    def __init__(
        self,
        configuration: EvalConfiguration,
        *,
        environ: Mapping[str, str] | None = None,
    ) -> None:
        if configuration.adapter != "subprocess":
            raise ValueError("SubprocessAdapter requires a subprocess configuration.")
        self._configuration = configuration
        self._environ = dict(os.environ if environ is None else environ)

    def reset(self) -> None:
        """Subprocess adapters have no deterministic replay state to reset."""

    def _subprocess_environment(self) -> dict[str, str] | None:
        missing = [name for name in self._configuration.required_env if not self._environ.get(name)]
        if missing:
            return None
        allowed = _SAFE_ENV_NAMES | set(self._configuration.required_env)
        return {name: value for name, value in self._environ.items() if name in allowed}

    def invoke(self, case: EvalCase) -> AdapterObservation:
        """Execute one bounded adapter request without a shell or raw-output retention."""
        environment = self._subprocess_environment()
        if environment is None:
            return _failure("adapter_unavailable")
        request = json.dumps(
            {
                "schema_version": 1,
                "case_id": case.id,
                "prompt": case.prompt,
            },
            separators=(",", ":"),
            sort_keys=True,
        )
        try:
            completed = subprocess.run(
                list(self._configuration.command),
                input=request,
                text=True,
                capture_output=True,
                timeout=self._configuration.limits.timeout_seconds,
                check=False,
                env=environment,
            )
        except subprocess.TimeoutExpired:
            return _failure("timeout")
        except OSError:
            return _failure("adapter_unavailable")

        try:
            payload = json.loads(completed.stdout)
            observation = _parse_adapter_payload(payload)
        except (json.JSONDecodeError, TypeError, ValueError):
            return _failure("protocol_error")
        if completed.returncode != 0 and observation.failure_kind is None:
            return _failure("protocol_error")
        return observation


def build_adapter(
    configuration: EvalConfiguration,
    *,
    environ: Mapping[str, str] | None = None,
) -> EvalAdapter:
    """Build the configured replay or subprocess adapter implementation."""
    if configuration.adapter == "replay":
        if configuration.trace_path is None:
            return ReplayAdapter(Path("/__missing_trace__"))
        return ReplayAdapter(configuration.trace_path)
    return SubprocessAdapter(configuration, environ=environ)

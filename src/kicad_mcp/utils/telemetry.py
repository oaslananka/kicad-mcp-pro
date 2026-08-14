"""OpenTelemetry runtime wiring for KiCad MCP Pro."""

from __future__ import annotations

import contextlib
import hashlib
import re
import threading
import time
import traceback
from collections import deque
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from urllib.parse import urlsplit, urlunsplit

from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import (
    OTLPMetricExporter as GrpcMetricExporter,
)
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
    OTLPSpanExporter as GrpcSpanExporter,
)
from opentelemetry.exporter.otlp.proto.http.metric_exporter import (
    OTLPMetricExporter as HttpMetricExporter,
)
from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
    OTLPSpanExporter as HttpSpanExporter,
)
from opentelemetry.metrics import Counter, Histogram, Meter, UpDownCounter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import MetricExporter, PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter
from opentelemetry.trace import Span, Status, StatusCode, Tracer

_SAFE_COMMAND_TOKEN = re.compile(r"^[A-Za-z0-9_.:-]+$")
_INSTRUMENTATION_SCOPE = "kicad-mcp-pro"
_DEFAULT_HTTP_OTLP_ENDPOINT = "http://127.0.0.1:4318"
_DEFAULT_GRPC_OTLP_ENDPOINT = "http://127.0.0.1:4317"
_SECRET_VALUE = re.compile(
    r"\b(api[_-]?key|token|access[_-]?token|refresh[_-]?token|client[_-]?secret|password|authorization)\s*[:=]\s*[^\s,;]+",
    re.IGNORECASE,
)
_URL = re.compile(r"\bhttps?://[^\s\"'<>]+", re.IGNORECASE)
_WINDOWS_PATH = re.compile(r"\b[A-Za-z]:\\[^\s\"'<>]+")
_POSIX_PRIVATE_PATH = re.compile(r"(^|[\s(\"'=])/(?:home|Users)/[^\s\"'<>),;]+")
_KICAD_FILE_PATH = re.compile(
    r"(^|[\s(\"'=])/[^\s\"'<>),;]+\.(?:kicad_pcb|kicad_sch|kicad_pro|kicad_dru|kicad_jobset|net|csv|xml|json|zip)\b",
    re.IGNORECASE,
)
_IP_ADDRESS = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_HOSTNAME = re.compile(
    r"\b(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+(?:[a-z]{2,63}|local|test)\b",
    re.IGNORECASE,
)
_VERSION = re.compile(r"\b(\d+)\.(\d+)(?:\.\d+)?\b")


@dataclass
class _TelemetryRuntime:
    configured: bool = False
    enabled: bool = False
    tracer: Tracer | None = None
    meter: Meter | None = None
    managed_tracer_provider: TracerProvider | None = None
    managed_meter_provider: MeterProvider | None = None
    tool_invocations: Counter | None = None
    tool_duration: Histogram | None = None
    session_active: UpDownCounter | None = None
    cli_invocations: Counter | None = None
    cli_duration: Histogram | None = None
    event_buffer: deque[dict[str, object]] = field(default_factory=deque)
    event_buffer_max_events: int = 0


_runtime = _TelemetryRuntime()
_runtime_lock = threading.Lock()


def _telemetry_requested(cfg: object) -> bool:
    return bool(getattr(cfg, "telemetry_enabled", False) or getattr(cfg, "otel_endpoint", None))


def _parse_headers(raw_headers: str) -> dict[str, str]:
    headers: dict[str, str] = {}
    for item in raw_headers.split(","):
        key, separator, value = item.partition("=")
        if not separator:
            continue
        normalized_key = key.strip()
        normalized_value = value.strip()
        if normalized_key and normalized_value:
            headers[normalized_key] = normalized_value
    return headers


def _http_signal_endpoint(endpoint: str | None, signal: str) -> str | None:
    if endpoint is None or endpoint == "":
        return None
    endpoint_text: str = endpoint
    parsed = urlsplit(endpoint_text)
    path = parsed.path.rstrip("/")
    desired = f"/v1/{signal}"
    if path == desired:
        return endpoint
    if path in {"", "/"}:
        new_path = desired
    elif path.endswith(("/v1/traces", "/v1/metrics")):
        new_path = f"{path.rsplit('/v1/', 1)[0]}{desired}"
    else:
        new_path = f"{path}{desired}"
    return urlunsplit((parsed.scheme, parsed.netloc, new_path, parsed.query, parsed.fragment))


def _endpoint_value(cfg: object) -> str | None:
    endpoint = getattr(cfg, "otel_endpoint", None)
    if endpoint not in (None, ""):
        return str(endpoint)
    protocol = str(getattr(cfg, "otel_protocol", "http/protobuf"))
    if protocol == "grpc":
        return _DEFAULT_GRPC_OTLP_ENDPOINT
    return _DEFAULT_HTTP_OTLP_ENDPOINT


def _resource(cfg: object) -> Resource:
    return Resource.create(
        {"service.name": str(getattr(cfg, "otel_service_name", "kicad-mcp-pro"))}
    )


def _configure_managed_tracer_provider(cfg: object, headers: Mapping[str, str]) -> TracerProvider:
    endpoint = _endpoint_value(cfg)
    protocol = str(getattr(cfg, "otel_protocol", "http/protobuf"))
    provider = TracerProvider(resource=_resource(cfg))
    if protocol == "grpc":
        exporter: SpanExporter = GrpcSpanExporter(endpoint=endpoint, headers=dict(headers) or None)
    else:
        exporter = HttpSpanExporter(
            endpoint=_http_signal_endpoint(endpoint, "traces"),
            headers=dict(headers) or None,
        )
    provider.add_span_processor(BatchSpanProcessor(exporter))
    return provider


def _configure_managed_meter_provider(cfg: object, headers: Mapping[str, str]) -> MeterProvider:
    endpoint = _endpoint_value(cfg)
    protocol = str(getattr(cfg, "otel_protocol", "http/protobuf"))
    if protocol == "grpc":
        exporter: MetricExporter = GrpcMetricExporter(
            endpoint=endpoint,
            headers=dict(headers) or None,
        )
    else:
        exporter = HttpMetricExporter(
            endpoint=_http_signal_endpoint(endpoint, "metrics"),
            headers=dict(headers) or None,
        )
    return MeterProvider(
        resource=_resource(cfg),
        metric_readers=[PeriodicExportingMetricReader(exporter)],
    )


def configure_telemetry(
    cfg: object,
    *,
    tracer_provider: TracerProvider | None = None,
    meter_provider: MeterProvider | None = None,
) -> None:
    """Configure the process-local telemetry runtime."""
    global _runtime
    with _runtime_lock:
        reset_telemetry(shutdown_managed=True)
        if not _telemetry_requested(cfg):
            _runtime = _TelemetryRuntime(configured=True)
            return

        headers = _parse_headers(str(getattr(cfg, "otel_headers", "") or ""))
        managed_tracer_provider = None
        managed_meter_provider = None
        active_tracer_provider = tracer_provider
        active_meter_provider = meter_provider
        if active_tracer_provider is None:
            managed_tracer_provider = _configure_managed_tracer_provider(cfg, headers)
            active_tracer_provider = managed_tracer_provider
        if active_meter_provider is None:
            managed_meter_provider = _configure_managed_meter_provider(cfg, headers)
            active_meter_provider = managed_meter_provider

        meter = active_meter_provider.get_meter(_INSTRUMENTATION_SCOPE)
        event_buffer_max_events = int(getattr(cfg, "telemetry_buffer_max_events", 100) or 0)
        _runtime = _TelemetryRuntime(
            configured=True,
            enabled=True,
            tracer=active_tracer_provider.get_tracer(_INSTRUMENTATION_SCOPE),
            meter=meter,
            managed_tracer_provider=managed_tracer_provider,
            managed_meter_provider=managed_meter_provider,
            event_buffer=deque(maxlen=event_buffer_max_events),
            event_buffer_max_events=event_buffer_max_events,
            tool_invocations=meter.create_counter(
                "mcp_tool_invocations_total",
                unit="{invocation}",
                description="MCP tool invocations by tool and status.",
            ),
            tool_duration=meter.create_histogram(
                "mcp_tool_duration_seconds",
                unit="s",
                description="MCP tool invocation duration.",
            ),
            session_active=meter.create_up_down_counter(
                "mcp_session_active",
                unit="{session}",
                description="Active Streamable HTTP MCP sessions.",
            ),
            cli_invocations=meter.create_counter(
                "kicad_cli_invocations_total",
                unit="{invocation}",
                description="KiCad CLI invocations by command and status.",
            ),
            cli_duration=meter.create_histogram(
                "kicad_cli_duration_seconds",
                unit="s",
                description="KiCad CLI invocation duration.",
            ),
        )


def ensure_telemetry_configured(cfg: object) -> None:
    """Configure telemetry once for server entrypoints."""
    with _runtime_lock:
        configured = _runtime.configured
        enabled = _runtime.enabled
    if not configured or (_telemetry_requested(cfg) and not enabled):
        configure_telemetry(cfg)


def reset_telemetry(*, shutdown_managed: bool = False) -> None:
    """Reset process-local telemetry state for tests and config reloads."""
    global _runtime
    managed_tracer_provider = _runtime.managed_tracer_provider
    managed_meter_provider = _runtime.managed_meter_provider
    _runtime = _TelemetryRuntime()
    if shutdown_managed:
        if managed_tracer_provider is not None:
            with contextlib.suppress(Exception):
                managed_tracer_provider.shutdown()
        if managed_meter_provider is not None:
            with contextlib.suppress(Exception):
                managed_meter_provider.shutdown()


def _current_runtime() -> _TelemetryRuntime:
    return _runtime


def _sanitize_text(value: str) -> str:
    return _SECRET_VALUE.sub(r"\1=[redacted]", value).replace("\x00", "").replace("\r", " ")


def _redact_text(value: str) -> str:
    return _sanitize_text(value).replace("\n", "\\n")


def _redact_payload_text(value: str) -> str:
    return _redact_text(value).replace("\t", " ")


def _redact_sensitive_text(value: str) -> str:
    text = _redact_payload_text(value)
    text = _URL.sub("[url]", text)
    text = _WINDOWS_PATH.sub("[path]", text)
    text = _POSIX_PRIVATE_PATH.sub(r"\1[path]", text)
    text = _KICAD_FILE_PATH.sub(r"\1[path]", text)
    text = _IP_ADDRESS.sub("[ip]", text)
    text = _HOSTNAME.sub("[host]", text)
    return text[:2000]


def _sanitize_attribute_key(key: str) -> str:
    sanitized = re.sub(r"[^A-Za-z0-9_.-]+", "_", key).strip("_")
    return sanitized[:80] or "attribute"


def _sanitize_attributes(attributes: Mapping[str, object] | None) -> dict[str, object]:
    if attributes is None:
        return {}
    sanitized: dict[str, object] = {}
    for key, value in attributes.items():
        safe_key = _sanitize_attribute_key(str(key))
        if value is None or isinstance(value, bool | int | float):
            sanitized[safe_key] = value
        elif isinstance(value, str):
            sanitized[safe_key] = _redact_sensitive_text(value)
        else:
            sanitized[safe_key] = _redact_sensitive_text(str(value))
    return sanitized


def tool_catalog_hash(tool_names: Iterator[str] | list[str] | tuple[str, ...]) -> str:
    """Return a stable, anonymous hash for the advertised MCP tool catalog."""
    digest = hashlib.sha256()
    for name in sorted(str(tool_name) for tool_name in tool_names):
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()[:16]


def kicad_cli_major_minor(version: str | None) -> str | None:
    """Extract only the KiCad CLI major.minor version from an arbitrary version string."""
    if not version:
        return None
    match = _VERSION.search(version)
    if match is None:
        return None
    return f"{match.group(1)}.{match.group(2)}"


def record_runtime_event(name: str, attributes: Mapping[str, object] | None = None) -> None:
    """Record a bounded, redacted telemetry event for offline retry/debug inspection."""
    runtime = _current_runtime()
    if not runtime.enabled or runtime.event_buffer_max_events == 0:
        return
    runtime.event_buffer.append(
        {
            "kind": "usage",
            "name": _redact_sensitive_text(name)[:120],
            "timestamp": time.time(),
            "attributes": _sanitize_attributes(attributes),
        }
    )


def record_error_event(
    name: str,
    error: BaseException,
    attributes: Mapping[str, object] | None = None,
) -> None:
    """Record a redacted error event without file paths, hostnames, tokens, or content."""
    runtime = _current_runtime()
    if not runtime.enabled or runtime.event_buffer_max_events == 0:
        return
    formatted_stack = "".join(
        traceback.format_exception(type(error), error, error.__traceback__, limit=12)
    )
    runtime.event_buffer.append(
        {
            "kind": "error",
            "name": _redact_sensitive_text(name)[:120],
            "timestamp": time.time(),
            "attributes": _sanitize_attributes(attributes),
            "error": {
                "type": _redact_sensitive_text(type(error).__name__),
                "message": _redact_sensitive_text(str(error)),
                "stack": _redact_sensitive_text(formatted_stack),
            },
        }
    )


def telemetry_buffer_snapshot() -> list[dict[str, object]]:
    """Return a copy of the redacted offline telemetry buffer for tests and diagnostics."""
    runtime = _current_runtime()
    if not runtime.enabled:
        return []
    return list(runtime.event_buffer)


def telemetry_enabled() -> bool:
    """Return True when process telemetry is currently enabled."""
    return _current_runtime().enabled


@contextlib.contextmanager
def tool_span(tool_name: str) -> Iterator[Span | None]:
    runtime = _current_runtime()
    if not runtime.enabled or runtime.tracer is None:
        yield None
        return
    with runtime.tracer.start_as_current_span(
        "mcp.tool",
        attributes={
            "rpc.system": "mcp",
            "rpc.method": "tools/call",
            "mcp.tool.name": tool_name,
        },
    ) as span:
        yield span


def finish_tool_span(span: Span | None, *, status: str, error_code: str | None) -> None:
    if span is None or not span.is_recording():
        return
    span.set_attribute("mcp.tool.status", status)
    if error_code is not None:
        span.set_attribute("error.type", error_code)
    if status != "ok":
        span.set_status(Status(StatusCode.ERROR, error_code or status))


def record_tool_invocation(tool_name: str, status: str, elapsed_seconds: float) -> None:
    runtime = _current_runtime()
    if not runtime.enabled:
        return
    attributes = {"tool": tool_name, "status": status}
    if runtime.tool_invocations is not None:
        runtime.tool_invocations.add(1, attributes)
    if runtime.tool_duration is not None:
        runtime.tool_duration.record(elapsed_seconds, {"tool": tool_name})


@contextlib.contextmanager
def mcp_request_span(
    *,
    http_method: str,
    mount_path: str,
    session_present: bool,
) -> Iterator[Span | None]:
    runtime = _current_runtime()
    if not runtime.enabled or runtime.tracer is None:
        yield None
        return
    with runtime.tracer.start_as_current_span(
        "mcp.request",
        attributes={
            "http.request.method": http_method,
            "url.path": mount_path,
            "rpc.system": "mcp",
            "mcp.session.present": session_present,
        },
    ) as span:
        yield span


def annotate_mcp_request(span: Span | None, *, rpc_method: str | None) -> None:
    if span is None or not span.is_recording() or rpc_method is None:
        return
    span.set_attribute("rpc.method", rpc_method)


def finish_mcp_request_span(span: Span | None, *, status_code: int | None) -> None:
    if span is None or not span.is_recording():
        return
    if status_code is not None:
        span.set_attribute("http.response.status_code", status_code)
        if status_code >= 500:
            span.set_status(Status(StatusCode.ERROR, str(status_code)))


def record_session_delta(delta: int) -> None:
    runtime = _current_runtime()
    if not runtime.enabled or runtime.session_active is None:
        return
    runtime.session_active.add(delta)


def safe_cli_command(args: tuple[str, ...]) -> str:
    """Return a path-free KiCad CLI command label."""
    tokens: list[str] = []
    for raw_token in args:
        token = str(raw_token).strip()
        if not token or token.startswith("-"):
            break
        if "/" in token or "\\" in token:
            break
        if not _SAFE_COMMAND_TOKEN.fullmatch(token):
            break
        tokens.append(token)
        if len(tokens) == 3:
            break
    return " ".join(tokens) if tokens else "unknown"


@contextlib.contextmanager
def cli_span(command: str) -> Iterator[Span | None]:
    runtime = _current_runtime()
    if not runtime.enabled or runtime.tracer is None:
        yield None
        return
    with runtime.tracer.start_as_current_span(
        "kicad.cli",
        attributes={
            "process.executable.name": "kicad-cli",
            "kicad.cli.command": command,
        },
    ) as span:
        yield span


def finish_cli_span(span: Span | None, *, status: str, return_code: int | None) -> None:
    if span is None or not span.is_recording():
        return
    span.set_attribute("kicad.cli.status", status)
    if return_code is not None:
        span.set_attribute("process.exit.code", return_code)
    if status != "ok":
        span.set_status(Status(StatusCode.ERROR, status))


def record_cli_invocation(command: str, status: str, elapsed_seconds: float) -> None:
    runtime = _current_runtime()
    if not runtime.enabled:
        return
    attributes = {"command": command, "status": status}
    if runtime.cli_invocations is not None:
        runtime.cli_invocations.add(1, attributes)
    if runtime.cli_duration is not None:
        runtime.cli_duration.record(elapsed_seconds, {"command": command})


@contextlib.contextmanager
def pcb_parse_span() -> Iterator[Span | None]:
    runtime = _current_runtime()
    if not runtime.enabled or runtime.tracer is None:
        yield None
        return
    with runtime.tracer.start_as_current_span("kicad.pcb.parse") as span:
        yield span


def finish_pcb_parse_span(
    span: Span | None, *, footprint_count: int, elapsed_seconds: float
) -> None:
    if span is None or not span.is_recording():
        return
    span.set_attribute("kicad.pcb.footprint_count", footprint_count)
    span.set_attribute("kicad.pcb.parse.duration_seconds", elapsed_seconds)

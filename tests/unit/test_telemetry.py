from __future__ import annotations

import subprocess
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import pytest
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader, MetricsData
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from starlette.testclient import TestClient

from kicad_mcp.compatibility import MCP_LEGACY_PROTOCOL_VERSION
from kicad_mcp.config import KiCadMCPConfig, get_config
from kicad_mcp.server import _apply_cli_env, build_server
from kicad_mcp.tools import board_file, export_support
from kicad_mcp.utils.telemetry import (
    configure_telemetry,
    kicad_cli_major_minor,
    record_error_event,
    record_runtime_event,
    reset_telemetry,
    telemetry_buffer_snapshot,
    tool_catalog_hash,
)
from tests.conftest import call_tool_text

HTTP_HEADERS = {
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
}


@pytest.fixture()
def telemetry_exporters() -> Iterable[
    tuple[InMemorySpanExporter, InMemoryMetricReader, MeterProvider]
]:
    span_exporter = InMemorySpanExporter()
    tracer_provider = TracerProvider()
    tracer_provider.add_span_processor(SimpleSpanProcessor(span_exporter))
    metric_reader = InMemoryMetricReader()
    meter_provider = MeterProvider(metric_readers=[metric_reader])
    configure_telemetry(
        KiCadMCPConfig(telemetry_enabled=True),
        tracer_provider=tracer_provider,
        meter_provider=meter_provider,
    )
    yield span_exporter, metric_reader, meter_provider
    reset_telemetry()
    tracer_provider.shutdown()
    meter_provider.shutdown()


def _metric_points(metrics_data: MetricsData, name: str) -> list[Any]:
    points: list[Any] = []
    for resource_metric in metrics_data.resource_metrics:
        for scope_metric in resource_metric.scope_metrics:
            for metric in scope_metric.metrics:
                if metric.name == name:
                    points.extend(metric.data.data_points)
    return points


def _metric_attributes(points: list[Any]) -> list[dict[str, object]]:
    return [dict(point.attributes or {}) for point in points]


def test_telemetry_config_enables_standard_otlp_env_and_cli_flag(
    sample_project: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del sample_project
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://collector.local:4318")
    monkeypatch.setenv("OTEL_SERVICE_NAME", "kicad-mcp-test")
    endpoint_cfg = KiCadMCPConfig()

    assert endpoint_cfg.telemetry_enabled is True
    assert endpoint_cfg.otel_endpoint == "http://collector.local:4318"
    assert endpoint_cfg.otel_service_name == "kicad-mcp-test"

    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    _apply_cli_env(telemetry=True)

    assert get_config().telemetry_enabled is True


def test_telemetry_disabled_does_not_buffer_runtime_events(sample_project: Path) -> None:
    del sample_project
    configure_telemetry(KiCadMCPConfig(telemetry_enabled=False))

    record_runtime_event(
        "mcp.tool_call",
        {
            "tool": "kicad_set_project",
            "project": "/home/alice/private/project",
        },
    )

    assert telemetry_buffer_snapshot() == []


def test_error_telemetry_buffer_is_bounded_and_redacted(sample_project: Path) -> None:
    private_file = sample_project / "private" / "board.kicad_pcb"
    cfg = KiCadMCPConfig(telemetry_enabled=True, telemetry_buffer_max_events=1)
    configure_telemetry(
        cfg,
        tracer_provider=TracerProvider(),
        meter_provider=MeterProvider(),
    )

    first_error = RuntimeError(
        f"failed to read {private_file} token=secret123 https://private.example.test"
    )
    second_error = ValueError(
        f"failed to parse {private_file} api_key=secret456 private.example.test"
    )
    record_error_event("mcp.tool_error", first_error, {"tool": "first"})
    record_error_event("mcp.tool_error", second_error, {"tool": "second"})

    buffered = telemetry_buffer_snapshot()
    payload_text = str(buffered)

    assert len(buffered) == 1
    assert buffered[0]["attributes"]["tool"] == "second"
    assert "[path]" in payload_text
    assert "[redacted]" in payload_text
    assert "[host]" in payload_text
    assert str(sample_project) not in payload_text
    assert "secret456" not in payload_text
    assert "private.example.test" not in payload_text


def test_runtime_context_helpers_are_stable_and_anonymous(sample_project: Path) -> None:
    del sample_project
    assert tool_catalog_hash(["kicad_set_project", "pcb_get_summary"]) == tool_catalog_hash(
        ["pcb_get_summary", "kicad_set_project"]
    )
    assert len(tool_catalog_hash(["kicad_set_project", "pcb_get_summary"])) == 16
    assert kicad_cli_major_minor("KiCad CLI 10.0.3-0") == "10.0"
    assert kicad_cli_major_minor("not a version") is None


@pytest.mark.anyio
async def test_tool_telemetry_exports_safe_spans_and_metrics(
    sample_project: Path,
    telemetry_exporters: tuple[InMemorySpanExporter, InMemoryMetricReader, MeterProvider],
) -> None:
    span_exporter, metric_reader, meter_provider = telemetry_exporters
    server = build_server("minimal")

    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})
    meter_provider.force_flush()

    tool_spans = [span for span in span_exporter.get_finished_spans() if span.name == "mcp.tool"]
    tool_metrics = _metric_attributes(
        _metric_points(metric_reader.get_metrics_data(), "mcp_tool_invocations_total")
    )
    duration_metrics = _metric_attributes(
        _metric_points(metric_reader.get_metrics_data(), "mcp_tool_duration_seconds")
    )

    assert tool_spans
    assert tool_spans[0].attributes["rpc.system"] == "mcp"
    assert tool_spans[0].attributes["rpc.method"] == "tools/call"
    assert tool_spans[0].attributes["mcp.tool.name"] == "kicad_set_project"
    assert str(sample_project) not in str(tool_spans[0].attributes)
    assert {"tool": "kicad_set_project", "status": "ok"} in tool_metrics
    assert {"tool": "kicad_set_project"} in duration_metrics


def test_cli_and_pcb_parser_telemetry_avoid_paths_and_content(
    sample_project: Path,
    telemetry_exporters: tuple[InMemorySpanExporter, InMemoryMetricReader, MeterProvider],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    span_exporter, metric_reader, meter_provider = telemetry_exporters
    private_output = sample_project / "private" / "board.gbr"

    def fake_run(
        args: list[str],
        *,
        capture_output: bool,
        text: bool,
        timeout: float,
        check: bool,
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        del capture_output, text, timeout, check
        _ = kwargs
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(export_support.subprocess, "run", fake_run)

    export_support._run_cli("pcb", "export", "gerbers", "--output", str(private_output))
    board_file._parse_board_footprint_blocks(
        '(kicad_pcb (footprint "R_0603" (property "Reference" "R1")))'
    )
    meter_provider.force_flush()

    cli_spans = [span for span in span_exporter.get_finished_spans() if span.name == "kicad.cli"]
    parser_spans = [
        span for span in span_exporter.get_finished_spans() if span.name == "kicad.pcb.parse"
    ]
    cli_metrics = _metric_attributes(
        _metric_points(metric_reader.get_metrics_data(), "kicad_cli_invocations_total")
    )

    assert cli_spans
    assert cli_spans[0].attributes["process.executable.name"] == "kicad-cli"
    assert cli_spans[0].attributes["kicad.cli.command"] == "pcb export gerbers"
    assert str(private_output) not in str(cli_spans[0].attributes)
    assert parser_spans
    assert "R1" not in str(parser_spans[0].attributes)
    assert {"command": "pcb export gerbers", "status": "ok"} in cli_metrics


def test_streamable_http_session_metric_tracks_active_sessions(
    sample_project: Path,
    telemetry_exporters: tuple[InMemorySpanExporter, InMemoryMetricReader, MeterProvider],
) -> None:
    del sample_project
    _span_exporter, metric_reader, meter_provider = telemetry_exporters
    cfg = get_config()
    cfg.transport = "streamable-http"
    cfg.stateful_http = True
    server = build_server("minimal")

    with TestClient(server.streamable_http_app(), base_url="http://127.0.0.1:3334") as client:
        initialized = client.post(
            "/mcp",
            headers=HTTP_HEADERS,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": MCP_LEGACY_PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": "telemetry-test", "version": "1.0.0"},
                },
            },
        )
    meter_provider.force_flush()

    session_points = _metric_points(metric_reader.get_metrics_data(), "mcp_session_active")

    assert initialized.status_code == 200
    assert initialized.headers.get("mcp-session-id")
    assert [point.value for point in session_points] == [1]

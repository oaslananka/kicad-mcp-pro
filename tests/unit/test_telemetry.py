from __future__ import annotations

import structlog

from kicad_mcp.telemetry.events import (
    emit_human_gate_reached,
    emit_quality_gate,
    emit_rollback,
    emit_tool_call_end,
    emit_tool_call_start,
)


def test_emit_tool_call_start_returns_timestamp() -> None:
    start = emit_tool_call_start(
        run_id="run-1",
        tool_name="sch_add_symbol",
        call_id="call-1",
        profile="schematic_only",
        dry_run=True,
        kicad_version="10.0.0",
        project_id="project-1",
    )

    assert isinstance(start, float)


def test_emit_functions_run_without_error() -> None:
    rollback_ref = "rollback-reference"
    emit_tool_call_end(
        run_id="run-1",
        tool_name="sch_add_symbol",
        call_id="call-1",
        ok=True,
        changed=False,
        dry_run=True,
        warning_count=1,
        artifact_count=0,
        duration_ms=12.345,
        human_gate_required=False,
    )
    emit_quality_gate(
        run_id="run-1",
        gate_id="gate-1",
        gate_name="project_quality_gate_report",
        passed=True,
    )
    emit_rollback(
        run_id="run-1",
        rollback_token=rollback_ref,
        restored_files=["demo.kicad_sch"],
    )
    emit_human_gate_reached(
        run_id="run-1",
        tool_name="export_manufacturing_package",
        reason="release approval",
    )


def test_structlog_capture_receives_event(monkeypatch) -> None:
    events: list[tuple[str, dict[str, object]]] = []

    class CapturingLogger:
        def info(self, event: str, **kwargs: object) -> None:
            events.append((event, kwargs))

        def warning(self, event: str, **kwargs: object) -> None:
            events.append((event, kwargs))

    monkeypatch.setattr(structlog, "get_logger", lambda _name: CapturingLogger())
    from kicad_mcp.telemetry import events as telemetry_events

    monkeypatch.setattr(telemetry_events, "logger", CapturingLogger())

    telemetry_events.emit_human_gate_reached(
        run_id="run-1",
        tool_name="export_manufacturing_package",
        reason="approval required",
    )

    assert events == [
        (
            "human_gate_required",
            {
                "run_id": "run-1",
                "tool_name": "export_manufacturing_package",
                "reason": "approval required",
            },
        )
    ]

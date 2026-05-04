"""Structured telemetry events for KiCad MCP Pro.

Events are emitted to local structured logs. No event is sent to an external service
without explicit operator configuration.
"""

from __future__ import annotations

import time

import structlog

logger = structlog.get_logger(__name__)


def emit_tool_call_start(
    *,
    run_id: str,
    tool_name: str,
    call_id: str,
    profile: str,
    dry_run: bool = False,
    kicad_version: str | None = None,
    project_id: str | None = None,
) -> float:
    """Emit a tool call start event and return the monotonic start timestamp."""
    start = time.monotonic()
    logger.info(
        "tool_call_start",
        run_id=run_id,
        tool_name=tool_name,
        call_id=call_id,
        profile=profile,
        dry_run=dry_run,
        kicad_version=kicad_version,
        project_id=project_id,
    )
    return start


def emit_tool_call_end(
    *,
    run_id: str,
    tool_name: str,
    call_id: str,
    ok: bool,
    changed: bool,
    dry_run: bool,
    warning_count: int = 0,
    error_class: str | None = None,
    artifact_count: int = 0,
    duration_ms: float,
    human_gate_required: bool = False,
) -> None:
    """Emit a tool call completion event."""
    logger.info(
        "tool_call_end",
        run_id=run_id,
        tool_name=tool_name,
        call_id=call_id,
        ok=ok,
        changed=changed,
        dry_run=dry_run,
        warning_count=warning_count,
        error_class=error_class,
        artifact_count=artifact_count,
        duration_ms=round(duration_ms, 2),
        human_gate_required=human_gate_required,
    )


def emit_quality_gate(
    *,
    run_id: str,
    gate_id: str,
    gate_name: str,
    passed: bool,
    erc_errors: int = 0,
    drc_errors: int = 0,
    dfm_violations: int = 0,
) -> None:
    """Emit a quality gate result event."""
    logger.info(
        "quality_gate",
        run_id=run_id,
        gate_id=gate_id,
        gate_name=gate_name,
        passed=passed,
        erc_errors=erc_errors,
        drc_errors=drc_errors,
        dfm_violations=dfm_violations,
    )


def emit_rollback(
    *,
    run_id: str,
    rollback_token: str,
    restored_files: list[str],
    triggered_by: str = "tool_failure",
) -> None:
    """Emit a rollback event."""
    logger.warning(
        "rollback_executed",
        run_id=run_id,
        rollback_token=rollback_token,
        restored_file_count=len(restored_files),
        triggered_by=triggered_by,
    )


def emit_human_gate_reached(
    *,
    run_id: str,
    tool_name: str,
    reason: str,
) -> None:
    """Emit when execution pauses for human approval."""
    logger.warning(
        "human_gate_required",
        run_id=run_id,
        tool_name=tool_name,
        reason=reason,
    )

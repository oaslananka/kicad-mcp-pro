"""Tests for the agent-facing design-workflow surface/state machine (#194/#195)."""

from __future__ import annotations

import pytest

from kicad_mcp.project.workflow import AGENT_WORKFLOW_PHASES, build_design_workflow
from kicad_mcp.server import build_server
from tests.conftest import call_tool_text


def test_fresh_workflow_starts_at_first_phase() -> None:
    state = build_design_workflow([])
    assert state.current_phase == "requirements_review"
    assert state.current_role == "Planner"
    assert state.overall_status == "READY"
    assert state.next_action == "project_get_design_spec()"
    assert len(state.phases) == len(AGENT_WORKFLOW_PHASES)
    assert state.phases[0].status == "READY"
    assert all(phase.status == "PENDING" for phase in state.phases[1:])


def test_completed_phases_advance_the_current_step() -> None:
    state = build_design_workflow(["requirements_review", "schematic_capture"])
    assert [p.status for p in state.phases[:2]] == ["COMPLETE", "COMPLETE"]
    assert state.phases[2].status == "READY"
    assert state.current_phase == state.phases[2].phase
    # Phases complete out of order still resolve to the first remaining one.
    skipped = build_design_workflow(["schematic_capture"])
    assert skipped.current_phase == "requirements_review"


def test_all_phases_complete_reports_release_ready() -> None:
    every_phase = [str(spec["phase"]) for spec in AGENT_WORKFLOW_PHASES]
    state = build_design_workflow(every_phase)
    assert state.overall_status == "COMPLETE"
    assert all(phase.status == "COMPLETE" for phase in state.phases)
    assert "ready for release" in state.next_action.lower()


def test_manufacturing_release_phase_is_human_gated() -> None:
    release = [p for p in build_design_workflow([]).phases if p.role == "Release Manager"]
    assert release and release[0].human_gate_required


@pytest.mark.anyio
async def test_project_design_workflow_tool_renders_phase_machine() -> None:
    server = build_server("agent_full")
    text = await call_tool_text(server, "project_design_workflow", {})
    assert "Professional PCB design workflow" in text
    assert "Current phase: requirements_review" in text

    advanced = await call_tool_text(
        server,
        "project_design_workflow",
        {"completed_phases": ["requirements_review"]},
    )
    assert "Current phase: schematic_capture" in advanced

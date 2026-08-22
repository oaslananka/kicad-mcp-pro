from __future__ import annotations


def test_workflow_service_preserves_phase_state_machine() -> None:
    from kicad_mcp.project.workflow import AGENT_WORKFLOW_PHASES, ProjectWorkflowService

    service = ProjectWorkflowService()
    state = service.build_state([])

    assert state.current_phase == "requirements_review"
    assert state.current_role == "Planner"
    assert state.overall_status == "READY"
    assert state.next_action == "project_get_design_spec()"
    assert len(state.phases) == len(AGENT_WORKFLOW_PHASES)
    assert state.phases[0].status == "READY"
    assert all(phase.status == "PENDING" for phase in state.phases[1:])


def test_workflow_service_preserves_completed_and_release_states() -> None:
    from kicad_mcp.project.workflow import AGENT_WORKFLOW_PHASES, ProjectWorkflowService

    service = ProjectWorkflowService()
    advanced = service.build_state(["requirements_review", "schematic_capture"])
    assert advanced.current_phase == "schematic_verification"
    assert [phase.status for phase in advanced.phases[:2]] == ["COMPLETE", "COMPLETE"]

    every_phase = [str(spec["phase"]) for spec in AGENT_WORKFLOW_PHASES]
    complete = service.build_state(every_phase)
    assert complete.overall_status == "COMPLETE"
    assert all(phase.status == "COMPLETE" for phase in complete.phases)
    assert "ready for release" in complete.next_action.lower()


def test_workflow_service_preserves_rendered_text() -> None:
    from kicad_mcp.project.workflow import ProjectWorkflowService

    text = ProjectWorkflowService().render(["requirements_review"])

    assert "Professional PCB design workflow" in text
    assert "Current phase: schematic_capture" in text
    assert "Overall status: READY" in text
    assert "[x] requirements_review" in text
    assert "[>] schematic_capture" in text

"""Project workflow state-machine behavior independent of FastMCP."""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from ..models.state import (
    DesignWorkflowState,
    WorkflowPhaseState,
    WorkflowPhaseStatus,
    WorkflowRole,
)

AGENT_WORKFLOW_PHASES: tuple[dict[str, object], ...] = (
    {
        "phase": "requirements_review",
        "role": "Planner",
        "high_level_tool": "review_requirements_and_missing_inputs",
        "next_action": "project_get_design_spec()",
        "gates": [],
    },
    {
        "phase": "schematic_capture",
        "role": "Builder",
        "high_level_tool": "create_schematic_from_intent",
        "next_action": "sch_build_circuit()",
        "gates": ["Schematic", "Connectivity"],
    },
    {
        "phase": "schematic_verification",
        "role": "Verifier",
        "high_level_tool": "verify_schematic_semantics",
        "next_action": "schematic_design_rule_check()",
        "gates": ["Schematic", "Connectivity"],
    },
    {
        "phase": "parts_and_footprints",
        "role": "Builder",
        "high_level_tool": "assign_parts_and_footprints_with_evidence",
        "next_action": "validate_footprints_vs_schematic()",
        "gates": ["PCB"],
    },
    {
        "phase": "constraints",
        "role": "Planner",
        "high_level_tool": "generate_board_constraints",
        "next_action": "drc_check_rule_conflicts()",
        "gates": ["DFM"],
    },
    {
        "phase": "placement",
        "role": "Builder",
        "high_level_tool": "place_board_professionally",
        "next_action": "pcb_placement_quality_report()",
        "gates": ["Placement"],
    },
    {
        "phase": "routing",
        "role": "Builder",
        "high_level_tool": "route_board_with_quality_gates",
        "next_action": "route_autoroute_freerouting()",
        "gates": ["PCB"],
    },
    {
        "phase": "full_verification",
        "role": "Verifier",
        "high_level_tool": "run_full_design_verification",
        "next_action": "project_quality_gate_report()",
        "gates": ["Schematic", "Connectivity", "PCB", "Placement", "DFM", "Manufacturing"],
    },
    {
        "phase": "fix_loop",
        "role": "Fixer",
        "high_level_tool": "fix_design_until_gate_passes",
        "next_action": "project_full_validation_loop()",
        "gates": ["Schematic", "Connectivity", "PCB", "Placement", "DFM", "Manufacturing"],
    },
    {
        "phase": "manufacturing_release",
        "role": "Release Manager",
        "high_level_tool": "prepare_manufacturing_release",
        "next_action": "export_manufacturing_package()",
        "gates": ["Manufacturing", "DFM"],
    },
)


def build_design_workflow(completed_phases: list[str]) -> DesignWorkflowState:
    """Build the typed design-workflow state from the phases already completed.

    The first phase not in ``completed_phases`` becomes ``READY`` (the current
    step); earlier ones are ``COMPLETE`` and later ones ``PENDING``. With every
    phase complete the last phase is reported as the current one.
    """
    completed = {name.strip() for name in completed_phases if name.strip()}
    phases: list[WorkflowPhaseState] = []
    current_index: int | None = None
    for index, spec in enumerate(AGENT_WORKFLOW_PHASES):
        name = str(spec["phase"])
        if name in completed:
            status: WorkflowPhaseStatus = "COMPLETE"
        elif current_index is None:
            status = "READY"
            current_index = index
        else:
            status = "PENDING"
        role = cast(WorkflowRole, spec["role"])
        phases.append(
            WorkflowPhaseState(
                phase=name,
                role=role,
                status=status,
                high_level_tool=str(spec["high_level_tool"]),
                next_action=str(spec["next_action"]),
                gates=list(cast("list[str]", spec["gates"])),
                human_gate_required=role == "Release Manager",
            )
        )

    if current_index is None:
        current = phases[-1]
        return DesignWorkflowState(
            current_phase=current.phase,
            current_role=current.role,
            overall_status="COMPLETE",
            phases=phases,
            next_action="All phases complete — the design is ready for release.",
            human_gate_required=False,
        )
    current = phases[current_index]
    return DesignWorkflowState(
        current_phase=current.phase,
        current_role=current.role,
        overall_status="READY",
        phases=phases,
        next_action=current.next_action,
        human_gate_required=current.human_gate_required,
    )


_PHASE_STATUS_MARKER: dict[WorkflowPhaseStatus, str] = {
    "COMPLETE": "x",
    "READY": ">",
    "PENDING": " ",
    "NEEDS_REVIEW": "?",
    "BLOCKED": "!",
}


def render_design_workflow(state: DesignWorkflowState) -> str:
    lines = [
        "Professional PCB design workflow",
        f"- Current phase: {state.current_phase} ({state.current_role})",
        f"- Overall status: {state.overall_status}",
        f"- Next action: {state.next_action}",
    ]
    if state.human_gate_required:
        lines.append("- Human gate required before this phase can complete.")
    lines.append("")
    lines.append("Phases:")
    for phase in state.phases:
        marker = _PHASE_STATUS_MARKER.get(phase.status, " ")
        gates = f" — gates: {', '.join(phase.gates)}" if phase.gates else ""
        lines.append(f"  [{marker}] {phase.phase} ({phase.role}) -> {phase.next_action}{gates}")
    return "\n".join(lines)


@dataclass(frozen=True, slots=True)
class ProjectWorkflowService:
    """Build and render the professional project workflow state machine."""

    def build_state(self, completed_phases: list[str]) -> DesignWorkflowState:
        return build_design_workflow(completed_phases)

    def render(self, completed_phases: list[str]) -> str:
        return render_design_workflow(self.build_state(completed_phases))

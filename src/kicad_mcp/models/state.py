"""Typed state for the agent-facing project design workflow."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


def _utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp."""
    return datetime.now(UTC)


WorkflowRole = Literal["Planner", "Builder", "Verifier", "Critic", "Fixer", "Release Manager"]
WorkflowPhaseStatus = Literal["PENDING", "READY", "COMPLETE", "NEEDS_REVIEW", "BLOCKED"]


class WorkflowGateState(BaseModel):
    """Immutable gate result attached to one workflow phase."""

    model_config = ConfigDict(frozen=True)

    name: str
    status: str
    summary: str = ""


class WorkflowPhaseState(BaseModel):
    """A typed lifecycle phase for agent-facing design workflows."""

    model_config = ConfigDict(frozen=True)

    phase: str
    role: WorkflowRole
    status: WorkflowPhaseStatus = "PENDING"
    high_level_tool: str
    next_action: str
    gates: list[str] = Field(default_factory=list)
    gate_results: list[WorkflowGateState] = Field(default_factory=list)
    human_gate_required: bool = False


class DesignWorkflowState(BaseModel):
    """Read-only state-machine snapshot for a professional PCB design run."""

    model_config = ConfigDict(frozen=True)

    current_phase: str
    current_role: WorkflowRole
    overall_status: WorkflowPhaseStatus
    phases: list[WorkflowPhaseState] = Field(default_factory=list)
    next_action: str = ""
    human_gate_required: bool = False
    generated_at: datetime = Field(default_factory=_utc_now)

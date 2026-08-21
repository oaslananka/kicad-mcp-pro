"""Thin FastMCP adapter for the professional project workflow."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from mcp.server.fastmcp import FastMCP

from .metadata import headless_compatible


class WorkflowService(Protocol):
    """Minimal project workflow service contract required by the adapter."""

    def render(self, completed_phases: list[str]) -> str: ...


@dataclass(frozen=True)
class ProjectWorkflowDependencies:
    """Project workflow dependencies injected by the composition root."""

    service: WorkflowService


def register(mcp: FastMCP, dependencies: ProjectWorkflowDependencies) -> None:
    """Register the professional project workflow tool."""
    service = dependencies.service

    @mcp.tool()
    @headless_compatible
    def project_design_workflow(completed_phases: list[str] | None = None) -> str:
        """Return the professional PCB design workflow as a typed phase state machine.

        Lays out the canonical Planner -> Builder -> Verifier -> Fixer -> Release
        sequence, with the high-level tool and the quality gates each phase must pass.
        Pass the phases already finished in ``completed_phases``; the tool marks them
        COMPLETE, reports the first remaining phase as READY (the current step) with
        its next action and gates, and flags when a human gate is required. Read-only
        and headless — use it to drive an autonomous design run step by step."""
        return service.render(completed_phases or [])

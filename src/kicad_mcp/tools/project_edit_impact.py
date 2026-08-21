"""Thin FastMCP adapter for project edit-impact assessment."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from mcp.server.fastmcp import FastMCP

from .metadata import headless_compatible


class EditImpactService(Protocol):
    def assess(self, baseline_spec_json: str = "") -> str: ...


@dataclass(frozen=True)
class ProjectEditImpactDependencies:
    service: EditImpactService


def register(mcp: FastMCP, dependencies: ProjectEditImpactDependencies) -> None:
    service = dependencies.service

    @mcp.tool()
    @headless_compatible
    def project_assess_edit_impact(baseline_spec_json: str = "") -> str:
        """Scope re-validation after an edit: semantic-diff the design intent and report
        which gates must re-run.

        Compares a baseline design spec — the declared/saved intent, or an explicit
        baseline passed as ``baseline_spec_json`` — against the intent inferred from the
        current board, then maps each change to the gates it can invalidate. Re-run only
        the impacted gates and keep the rest as already-proven. Use after editing an
        existing project so a small change does not force a full re-validation."""
        return service.assess(baseline_spec_json)

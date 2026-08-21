"""Thin FastMCP adapter for read-only project reporting."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from mcp.server.fastmcp import FastMCP

from ..project.reporting import DesignReportPayload
from .metadata import headless_compatible


class ProjectReportingServiceLike(Protocol):
    def gate_trend(self, gate_name: str, last_n: int = 10) -> str: ...

    def design_report(self) -> DesignReportPayload: ...


@dataclass(frozen=True)
class ProjectReportingDependencies:
    service: ProjectReportingServiceLike


def register(mcp: FastMCP, dependencies: ProjectReportingDependencies) -> None:
    service = dependencies.service

    @mcp.tool()
    @headless_compatible
    def project_gate_trend(gate_name: str, last_n: int = 10) -> str:
        """Return persisted quality-gate trend history for one gate."""
        return service.gate_trend(gate_name, last_n)

    @mcp.tool()
    @headless_compatible
    def project_design_report() -> DesignReportPayload:
        """Generate a comprehensive design-status report.

        Combines intent summary, v2 spec richness, project gate evaluation, and
        a prioritised list of next steps into a single structured report.
        This is the recommended first call after opening a project to understand
        its current state.
        """
        return service.design_report()

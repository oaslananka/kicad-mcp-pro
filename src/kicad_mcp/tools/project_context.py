"""FastMCP adapter for active project context tools."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from mcp.server.fastmcp import FastMCP

from .metadata import headless_compatible


class ProjectContextServiceProtocol(Protocol):
    def set_project(
        self,
        project_dir: str,
        pcb_file: str = "",
        sch_file: str = "",
        output_dir: str = "",
    ) -> str: ...

    def get_project_info(self) -> str: ...


@dataclass(frozen=True, slots=True)
class ProjectContextDependencies:
    service: ProjectContextServiceProtocol


def register(mcp: FastMCP, deps: ProjectContextDependencies) -> None:
    """Register active project context tools at their legacy public position."""

    @mcp.tool()
    @headless_compatible
    def kicad_set_project(
        project_dir: str,
        pcb_file: str = "",
        sch_file: str = "",
        output_dir: str = "",
    ) -> str:
        """Set the active KiCad project directory and file paths."""
        return deps.service.set_project(project_dir, pcb_file, sch_file, output_dir)

    @mcp.tool()
    @headless_compatible
    def kicad_get_project_info() -> str:
        """Show the currently configured KiCad project paths."""
        return deps.service.get_project_info()

"""FastMCP adapter for the startup quick-start guide tool."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from mcp.server.fastmcp import FastMCP

from .metadata import headless_compatible


class ProjectHelpServiceProtocol(Protocol):
    def help_text(self) -> str: ...


@dataclass(frozen=True, slots=True)
class ProjectHelpDependencies:
    service: ProjectHelpServiceProtocol


def register(mcp: FastMCP, deps: ProjectHelpDependencies) -> None:
    """Register the startup quick-start guide tool at its legacy public position."""

    @mcp.tool()
    @headless_compatible
    def kicad_help() -> str:
        """Show a concise startup guide and all tool categories."""
        return deps.service.help_text()

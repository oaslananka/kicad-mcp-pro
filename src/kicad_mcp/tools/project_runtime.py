"""FastMCP adapter for project runtime diagnostics."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from mcp.server.fastmcp import FastMCP

from .metadata import headless_compatible


class ProjectRuntimeServiceProtocol(Protocol):
    def version_info(self) -> str: ...


@dataclass(frozen=True, slots=True)
class ProjectRuntimeDependencies:
    service: ProjectRuntimeServiceProtocol


def register(mcp: FastMCP, deps: ProjectRuntimeDependencies) -> None:
    """Register project runtime diagnostics at their legacy public position."""

    @mcp.tool()
    @headless_compatible
    def kicad_get_version() -> str:
        """Get KiCad version information and current connection status."""
        return deps.service.version_info()

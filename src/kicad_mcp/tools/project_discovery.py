"""FastMCP adapter for project discovery tools."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field

from .metadata import headless_compatible


class ScanDirectoryInput(BaseModel):
    """Directory scan parameters."""

    path: str = Field(min_length=1, max_length=1000)


class ProjectDiscoveryServiceProtocol(Protocol):
    def list_recent_projects(self) -> str: ...

    def scan_directory(self, path: str) -> str: ...


@dataclass(frozen=True, slots=True)
class ProjectDiscoveryDependencies:
    service: ProjectDiscoveryServiceProtocol


def register(mcp: FastMCP, deps: ProjectDiscoveryDependencies) -> None:
    """Register project discovery tools at their legacy public position."""

    @mcp.tool()
    @headless_compatible
    def kicad_list_recent_projects() -> str:
        """List recently opened KiCad projects from KiCad's config files."""
        return deps.service.list_recent_projects()

    @mcp.tool()
    @headless_compatible
    def kicad_scan_directory(path: str) -> str:
        """Scan a directory and report any KiCad project files it contains."""
        payload = ScanDirectoryInput(path=path)
        return deps.service.scan_directory(payload.path)

"""FastMCP adapter for project creation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field

from .metadata import headless_compatible


class CreateProjectInput(BaseModel):
    """New project creation parameters."""

    path: str = Field(min_length=1, max_length=1000)
    name: str = Field(min_length=1, max_length=120)


class ProjectCreationServiceProtocol(Protocol):
    def create(self, path: str, name: str, *, confirm_overwrite: bool = False) -> str: ...


@dataclass(frozen=True, slots=True)
class ProjectCreationDependencies:
    service: ProjectCreationServiceProtocol


def register(mcp: FastMCP, deps: ProjectCreationDependencies) -> None:
    """Register project creation at its legacy public position."""

    @mcp.tool()
    @headless_compatible
    def kicad_create_new_project(path: str, name: str, confirm_overwrite: bool = False) -> str:
        """Create a new minimal KiCad project structure and activate it."""
        payload = CreateProjectInput(path=path, name=name)
        return deps.service.create(
            payload.path,
            payload.name,
            confirm_overwrite=confirm_overwrite,
        )

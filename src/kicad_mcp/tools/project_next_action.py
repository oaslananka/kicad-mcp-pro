"""Thin FastMCP adapter for project next-action recommendation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from mcp.server.fastmcp import FastMCP

from ..project.next_action import ProjectNextActionPayload
from .metadata import headless_compatible


class NextActionService(Protocol):
    def next_action(self) -> ProjectNextActionPayload: ...


@dataclass(frozen=True)
class ProjectNextActionDependencies:
    service: NextActionService


def register(mcp: FastMCP, dependencies: ProjectNextActionDependencies) -> None:
    service = dependencies.service

    @mcp.tool()
    @headless_compatible
    def project_get_next_action() -> ProjectNextActionPayload:
        """Return the next high-priority action derived from the current project gate."""
        return service.next_action()

"""Thin FastMCP adapter for PCB group inspection."""

# pyright: reportUnusedFunction=false

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from mcp.server.fastmcp import FastMCP

from .metadata import headless_compatible


class GroupsInspectionService(Protocol):
    """Minimal service contract required by the groups adapter."""

    def get_groups(self) -> str: ...


@dataclass(frozen=True)
class PcbGroupsInspectionDependencies:
    """PCB groups dependencies injected by the composition root."""

    service: GroupsInspectionService


def register(mcp: FastMCP, dependencies: PcbGroupsInspectionDependencies) -> None:
    """Register PCB group inspection tools."""
    service = dependencies.service

    @mcp.tool()
    @headless_compatible
    def pcb_get_groups() -> str:
        """List board groups (KiCad 10.0.0+).

        Groups are logical collections of board items that can be moved and
        manipulated together.

        Returns:
            JSON string with group information or message if not supported.
        """
        return service.get_groups()

"""Thin FastMCP adapters for PCB session inspection."""

# pyright: reportUnusedFunction=false

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from mcp.server.fastmcp import FastMCP

from .metadata import headless_compatible


class SessionInspectionService(Protocol):
    """Minimal service contract required by the session adapter."""

    def get_selection(self) -> str: ...

    def get_board_as_string(self) -> str: ...


@dataclass(frozen=True)
class PcbSessionInspectionDependencies:
    """PCB session dependencies injected by the composition root."""

    service: SessionInspectionService


def register(mcp: FastMCP, dependencies: PcbSessionInspectionDependencies) -> None:
    """Register PCB session inspection tools."""
    service = dependencies.service

    @mcp.tool()
    @headless_compatible
    def pcb_get_selection() -> str:
        """List currently selected items in the PCB editor."""
        return service.get_selection()

    @mcp.tool()
    @headless_compatible
    def pcb_get_board_as_string() -> str:
        """Return the current board as a bounded S-expression string."""
        return service.get_board_as_string()

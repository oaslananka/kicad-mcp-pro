"""Thin FastMCP adapters for PCB stackup management."""

# pyright: reportUnusedFunction=false

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from mcp.server.mcpserver import MCPServer as FastMCP

from .metadata import headless_compatible


class StackupService(Protocol):
    """Minimal stackup service contract required by the adapter."""

    def get_stackup(self) -> str: ...

    def set_stackup(
        self, layers: list[dict[str, object]], allow_open_board: bool = False
    ) -> str: ...


@dataclass(frozen=True)
class PcbStackupDependencies:
    """Stackup dependencies injected by the PCB composition root."""

    service: StackupService


def register(mcp: FastMCP, dependencies: PcbStackupDependencies) -> None:
    """Register PCB stackup inspection and programming tools."""
    service = dependencies.service

    @mcp.tool()
    @headless_compatible
    def pcb_get_stackup() -> str:
        """Show the current stackup."""
        return service.get_stackup()

    @mcp.tool()
    @headless_compatible
    def pcb_set_stackup(layers: list[dict[str, object]], allow_open_board: bool = False) -> str:
        """Set the active board stackup using a file-backed profile.

        File-based: refuses while the board is open in KiCad unless
        ``allow_open_board=True``, which makes KiCad reload the file afterwards.
        """
        return service.set_stackup(layers, allow_open_board=allow_open_board)

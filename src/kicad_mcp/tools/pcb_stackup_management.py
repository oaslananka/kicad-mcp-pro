"""Thin FastMCP adapters for PCB stackup management."""

# pyright: reportUnusedFunction=false

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from mcp.server.fastmcp import FastMCP

from .metadata import headless_compatible


class StackupService(Protocol):
    """Minimal stackup service contract required by the adapter."""

    def get_stackup(self) -> str: ...

    def set_stackup(self, layers: list[dict[str, object]]) -> str: ...


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
    def pcb_set_stackup(layers: list[dict[str, object]]) -> str:
        """Set the active board stackup using a file-backed profile."""
        return service.set_stackup(layers)

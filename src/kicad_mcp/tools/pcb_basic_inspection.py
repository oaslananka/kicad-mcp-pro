"""Thin FastMCP adapters for basic PCB collection inspection."""

# pyright: reportUnusedFunction=false

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from mcp.server.fastmcp import FastMCP

from .metadata import headless_compatible, requires_kicad_running


class BasicInspectionService(Protocol):
    """Minimal service contract required by the adapter."""

    def get_nets(self) -> str: ...

    def get_zones(self) -> str: ...

    def get_shapes(self) -> str: ...

    def get_pads(self) -> str: ...

    def get_layers(self) -> str: ...


@dataclass(frozen=True)
class PcbBasicInspectionDependencies:
    """Basic PCB inspection dependencies injected by the composition root."""

    service: BasicInspectionService


def register(mcp: FastMCP, dependencies: PcbBasicInspectionDependencies) -> None:
    """Register basic PCB collection inspection tools."""
    service = dependencies.service

    @mcp.tool()
    @headless_compatible
    def pcb_get_nets() -> str:
        """List all board nets."""
        return service.get_nets()

    @mcp.tool()
    @headless_compatible
    def pcb_get_zones() -> str:
        """List all board copper zones."""
        return service.get_zones()

    @mcp.tool()
    @requires_kicad_running
    def pcb_get_shapes() -> str:
        """List graphical board shapes."""
        return service.get_shapes()

    @mcp.tool()
    @requires_kicad_running
    def pcb_get_pads() -> str:
        """List board pads."""
        return service.get_pads()

    @mcp.tool()
    @headless_compatible
    def pcb_get_layers() -> str:
        """List enabled board layers."""
        return service.get_layers()

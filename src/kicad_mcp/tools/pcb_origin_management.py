"""Thin FastMCP adapters for PCB drill-origin tools."""

# pyright: reportUnusedFunction=false

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from mcp.server.fastmcp import FastMCP

from .metadata import headless_compatible, requires_kicad_running


class OriginService(Protocol):
    """Minimal service contract required by the origin adapter."""

    def set_origin(self, x_mm: float, y_mm: float) -> str: ...

    def get_origin(self) -> str: ...


@dataclass(frozen=True)
class PcbOriginDependencies:
    """PCB origin dependencies injected by the composition root."""

    service: OriginService


def register(mcp: FastMCP, dependencies: PcbOriginDependencies) -> None:
    """Register PCB drill-origin tools."""
    service = dependencies.service

    @mcp.tool()
    @requires_kicad_running
    def pcb_set_origin(x_mm: float, y_mm: float) -> str:
        """Set the board origin (drill origin) in millimeters.

        The origin is used as the reference point for drill files and some
        export formats.

        Args:
            x_mm: X coordinate in millimeters.
            y_mm: Y coordinate in millimeters.

        Returns:
            Confirmation message with new origin coordinates.
        """
        return service.set_origin(x_mm, y_mm)

    @mcp.tool()
    @headless_compatible
    def pcb_get_origin() -> str:
        """Get the current board origin (drill origin) in millimeters.

        Returns:
            JSON string with origin coordinates or message if not supported.
        """
        return service.get_origin()

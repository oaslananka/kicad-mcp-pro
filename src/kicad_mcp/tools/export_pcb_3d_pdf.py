"""Thin FastMCP adapter for PCB 3D PDF export."""

# pyright: reportUnusedFunction=false

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from mcp.server.fastmcp import FastMCP

from .metadata import headless_compatible


class Pcb3dPdfService(Protocol):
    """Minimal service contract required by the PCB 3D PDF adapter."""

    def export(self, output_path: str = "") -> str: ...


@dataclass(frozen=True)
class ExportPcb3dPdfDependencies:
    """PCB 3D PDF dependencies injected by the export composition root."""

    service: Pcb3dPdfService
    add_low_level_notice: Callable[[str], str]


def register(mcp: FastMCP, dependencies: ExportPcb3dPdfDependencies) -> None:
    """Register the PCB 3D PDF export tool."""
    service = dependencies.service
    add_low_level_notice = dependencies.add_low_level_notice

    @mcp.tool()
    @headless_compatible
    def pcb_export_3d_pdf(output_path: str = "") -> str:
        """Export the PCB to a 3D PDF.

        Parameters
        ----------
        output_path : str
            Output file name (relative to the export output directory)."""
        return add_low_level_notice(service.export(output_path))

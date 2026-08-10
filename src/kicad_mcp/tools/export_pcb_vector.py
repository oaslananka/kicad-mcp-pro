"""Thin FastMCP adapter for PCB SVG/DXF exports."""

# pyright: reportUnusedFunction=false

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from mcp.server.fastmcp import FastMCP

from .metadata import headless_compatible


class PcbVectorService(Protocol):
    """Minimal service contract required by the PCB vector adapter."""

    def export_svg(self, layer: str = "F.Cu") -> str: ...

    def export_dxf(self, layer: str = "Edge.Cuts") -> str: ...


@dataclass(frozen=True)
class ExportPcbVectorDependencies:
    """PCB vector dependencies injected by the export composition root."""

    service: PcbVectorService
    add_low_level_notice: Callable[[str], str]


def register(mcp: FastMCP, dependencies: ExportPcbVectorDependencies) -> None:
    """Register PCB SVG and DXF export tools."""
    service = dependencies.service
    add_low_level_notice = dependencies.add_low_level_notice

    @mcp.tool()
    @headless_compatible
    def export_svg(layer: str = "F.Cu") -> str:
        """Export a board layer to SVG when supported."""
        return add_low_level_notice(service.export_svg(layer))

    @mcp.tool()
    @headless_compatible
    def export_dxf(layer: str = "Edge.Cuts") -> str:
        """Export a board layer to DXF when supported."""
        return add_low_level_notice(service.export_dxf(layer))

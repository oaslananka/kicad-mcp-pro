"""Thin FastMCP adapter for schematic SVG/DXF exports."""

# pyright: reportUnusedFunction=false

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from mcp.server.fastmcp import FastMCP

from .metadata import headless_compatible


class SchVectorService(Protocol):
    """Minimal service contract required by the schematic vector adapter."""

    def export_svg(self) -> str: ...

    def export_dxf(self) -> str: ...


@dataclass(frozen=True)
class ExportSchVectorDependencies:
    """Schematic vector dependencies injected by the export composition root."""

    service: SchVectorService
    add_low_level_notice: Callable[[str], str]


def register(mcp: FastMCP, dependencies: ExportSchVectorDependencies) -> None:
    """Register schematic SVG and DXF export tools."""
    service = dependencies.service
    add_low_level_notice = dependencies.add_low_level_notice

    @mcp.tool()
    @headless_compatible
    def export_sch_svg() -> str:
        """Export the schematic to SVG when supported."""
        return add_low_level_notice(service.export_svg())

    @mcp.tool()
    @headless_compatible
    def export_sch_dxf() -> str:
        """Export the schematic to DXF when supported."""
        return add_low_level_notice(service.export_dxf())

"""Thin FastMCP adapter for PCB PDF export."""

# pyright: reportUnusedFunction=false

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from mcp.server.fastmcp import FastMCP

from .metadata import headless_compatible


class PcbPdfService(Protocol):
    """Minimal service contract required by the PCB PDF adapter."""

    def export(self, layers: list[str] | None = None) -> str: ...


@dataclass(frozen=True)
class ExportPcbPdfDependencies:
    """PCB PDF dependencies injected by the export composition root."""

    service: PcbPdfService
    add_low_level_notice: Callable[[str], str]


def register(mcp: FastMCP, dependencies: ExportPcbPdfDependencies) -> None:
    """Register the PCB PDF export tool."""
    service = dependencies.service
    add_low_level_notice = dependencies.add_low_level_notice

    @mcp.tool()
    @headless_compatible
    def export_pcb_pdf(layers: list[str] | None = None) -> str:
        """Export the PCB to PDF."""
        return add_low_level_notice(service.export(layers))

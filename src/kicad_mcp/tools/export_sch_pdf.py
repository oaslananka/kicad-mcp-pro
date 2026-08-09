"""Thin FastMCP adapter for schematic PDF export."""

# pyright: reportUnusedFunction=false

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from mcp.server.fastmcp import FastMCP

from .metadata import headless_compatible


class SchPdfService(Protocol):
    """Minimal service contract required by the schematic PDF adapter."""

    def export(self) -> str: ...


@dataclass(frozen=True)
class ExportSchPdfDependencies:
    """Schematic PDF dependencies injected by the export composition root."""

    service: SchPdfService
    add_low_level_notice: Callable[[str], str]


def register(mcp: FastMCP, dependencies: ExportSchPdfDependencies) -> None:
    """Register the schematic PDF export tool."""
    service = dependencies.service
    add_low_level_notice = dependencies.add_low_level_notice

    @mcp.tool()
    @headless_compatible
    def export_sch_pdf() -> str:
        """Export the schematic to PDF."""
        return add_low_level_notice(service.export())

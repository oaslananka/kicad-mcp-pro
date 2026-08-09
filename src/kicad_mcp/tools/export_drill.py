"""Thin FastMCP adapter for PCB drill export."""

# pyright: reportUnusedFunction=false

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from mcp.server.fastmcp import FastMCP

from .metadata import headless_compatible


class DrillService(Protocol):
    """Minimal service contract required by the drill adapter."""

    def export(self, output_subdir: str = "gerber", variant_name: str | None = None) -> str: ...


@dataclass(frozen=True)
class ExportDrillDependencies:
    """Drill-export dependencies injected by the export composition root."""

    service: DrillService
    add_low_level_notice: Callable[[str], str]


def register(mcp: FastMCP, dependencies: ExportDrillDependencies) -> None:
    """Register the PCB drill export tool."""
    service = dependencies.service
    add_low_level_notice = dependencies.add_low_level_notice

    @mcp.tool()
    @headless_compatible
    def export_drill(output_subdir: str = "gerber") -> str:
        """Export drill files."""
        return add_low_level_notice(service.export(output_subdir))

"""Thin FastMCP adapter for schematic legacy Python BOM export."""

# pyright: reportUnusedFunction=false

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from mcp.server.fastmcp import FastMCP

from .metadata import headless_compatible


class SchPythonBomService(Protocol):
    """Minimal service contract required by the schematic Python BOM adapter."""

    def export(self, output_file: str = "") -> str: ...


@dataclass(frozen=True)
class ExportSchPythonBomDependencies:
    """Schematic Python BOM dependencies injected by the export composition root."""

    service: SchPythonBomService
    add_low_level_notice: Callable[[str], str]


def register(mcp: FastMCP, dependencies: ExportSchPythonBomDependencies) -> None:
    """Register the schematic legacy Python BOM export tool."""
    service = dependencies.service
    add_low_level_notice = dependencies.add_low_level_notice

    @mcp.tool()
    @headless_compatible
    def export_sch_python_bom() -> str:
        """Export the schematic BOM using KiCad's Python BOM engine."""
        return add_low_level_notice(service.export())

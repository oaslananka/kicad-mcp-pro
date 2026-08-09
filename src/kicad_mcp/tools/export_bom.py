"""Thin FastMCP adapter for BOM export."""

# pyright: reportUnusedFunction=false

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from mcp.server.fastmcp import FastMCP

from .metadata import headless_compatible


class BomService(Protocol):
    """Minimal service contract required by the BOM adapter."""

    def export(self, format: str = "csv", variant_name: str | None = None) -> str: ...


@dataclass(frozen=True)
class ExportBomDependencies:
    """BOM-export dependencies injected by the export composition root."""

    service: BomService
    add_low_level_notice: Callable[[str], str]


def register(mcp: FastMCP, dependencies: ExportBomDependencies) -> None:
    """Register the BOM export tool."""
    service = dependencies.service
    add_low_level_notice = dependencies.add_low_level_notice

    @mcp.tool()
    @headless_compatible
    def export_bom(format: str = "csv") -> str:
        """Export a bill of materials."""
        return add_low_level_notice(service.export(format))

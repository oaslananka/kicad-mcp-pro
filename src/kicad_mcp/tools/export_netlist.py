"""Thin FastMCP adapters for schematic netlist export tools."""

# pyright: reportUnusedFunction=false

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from mcp.server.fastmcp import FastMCP

from .metadata import headless_compatible


class NetlistService(Protocol):
    """Minimal service contract required by the netlist adapter."""

    def export(self, format_name: str = "kicad") -> str: ...


@dataclass(frozen=True)
class ExportNetlistDependencies:
    """Netlist dependencies injected by the export composition root."""

    service: NetlistService
    add_low_level_notice: Callable[[str], str]


def register(mcp: FastMCP, dependencies: ExportNetlistDependencies) -> None:
    """Register schematic netlist export tools."""
    service = dependencies.service
    add_low_level_notice = dependencies.add_low_level_notice

    @mcp.tool()
    @headless_compatible
    def export_netlist(format: str = "kicad") -> str:
        """Export a KiCad schematic netlist."""
        return add_low_level_notice(service.export(format))

    @mcp.tool()
    @headless_compatible
    def export_spice_netlist() -> str:
        """Export a SPICE netlist."""
        return add_low_level_notice(service.export("spice"))

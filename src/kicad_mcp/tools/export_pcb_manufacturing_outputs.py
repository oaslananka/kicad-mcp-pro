"""Thin FastMCP adapter for low-level PCB manufacturing output exports."""

# pyright: reportUnusedFunction=false

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from mcp.server.fastmcp import FastMCP

from ..export.pcb_manufacturing_outputs import ExportPcbManufacturingOutputsService
from .metadata import headless_compatible


@dataclass(frozen=True)
class ExportPcbManufacturingOutputsDependencies:
    """Low-level manufacturing export service and public debug notice."""

    service: ExportPcbManufacturingOutputsService
    add_low_level_notice: Callable[[str], str]


def register(mcp: FastMCP, dependencies: ExportPcbManufacturingOutputsDependencies) -> None:
    """Register low-level PCB manufacturing output tools."""
    service = dependencies.service
    add_low_level_notice = dependencies.add_low_level_notice

    @mcp.tool()
    @headless_compatible
    def export_pick_and_place(format: str = "csv", variant: str | None = None) -> str:
        """Export pick and place (CPL) data for the active PCB.

        Parameters
        ----------
        format : str
            Output format (e.g. ``csv``, ``ascii``).
        variant : str | None
            Optional design variant name. When set, exports variant-specific
            pick-and-place data (component population, value, footprint
            overrides). Uses the active variant when omitted.
        """
        return add_low_level_notice(
            service.export_pick_and_place(format=format, variant_name=variant)
        )

    @mcp.tool()
    @headless_compatible
    def export_ipc2581() -> str:
        """Export the active PCB to IPC-2581 format."""
        return add_low_level_notice(service.export_ipc2581())

    @mcp.tool()
    @headless_compatible
    def export_odb() -> str:
        """Export the active PCB to ODB++ format."""
        return add_low_level_notice(service.export_odb())

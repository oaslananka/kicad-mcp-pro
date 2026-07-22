"""Thin FastMCP adapters for schematic hierarchy and connectivity inspection."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from ..models.schematic import GetSheetInfoInput, TraceNetInput
from ..schematic.topology import SchematicTopologyService

type ActiveSchematicFile = Callable[[], Path]


@dataclass(frozen=True)
class SchematicTopologyDependencies:
    """Existing topology dependencies injected by the composition root."""

    active_schematic_file: ActiveSchematicFile
    service: SchematicTopologyService


def register(mcp: FastMCP, dependencies: SchematicTopologyDependencies) -> None:
    """Register the read-only schematic topology tranche."""
    service = dependencies.service

    @mcp.tool()
    def sch_list_sheets() -> str:
        """List child sheets from the active top-level schematic."""
        return service.list_sheets(dependencies.active_schematic_file())

    @mcp.tool()
    def sch_get_sheet_info(sheet_name: str) -> str:
        """Return metadata for a specific child sheet."""
        payload = GetSheetInfoInput(sheet_name=sheet_name)
        return service.sheet_info(
            dependencies.active_schematic_file(),
            payload.sheet_name,
        )

    @mcp.tool()
    def sch_get_connectivity_graph() -> str:
        """Summarize the active schematic as a textual net connectivity graph."""
        return service.connectivity_graph(dependencies.active_schematic_file())

    @mcp.tool()
    def sch_trace_net(net_name: str) -> str:
        """Trace a named net through the active schematic and matching child sheets."""
        payload = TraceNetInput(net_name=net_name)
        return service.trace_net(
            dependencies.active_schematic_file(),
            payload.net_name,
        )

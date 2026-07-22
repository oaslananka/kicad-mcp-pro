"""Thin FastMCP adapters for read-only schematic inspection tools."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from mcp.server.fastmcp import FastMCP

from ..schematic.inspection import SchematicInspectionService
from ..utils.cache import ttl_cache
from .metadata import headless_compatible


class ResolvedSchematicTarget(Protocol):
    """Minimal target contract required by inspection registration."""

    path: Path


type ResolveSchematicTarget = Callable[..., ResolvedSchematicTarget]
type ActiveSchematicFile = Callable[[], Path]


@dataclass(frozen=True)
class SchematicInspectionDependencies:
    """Existing schematic dependencies injected by the composition root."""

    resolve_target: ResolveSchematicTarget
    active_schematic_file: ActiveSchematicFile
    service: SchematicInspectionService


def register(mcp: FastMCP, dependencies: SchematicInspectionDependencies) -> None:
    """Register the read-only schematic inspection tranche."""
    service = dependencies.service

    @mcp.tool()
    @ttl_cache(ttl_seconds=5)
    def sch_get_symbols(
        sheet: str | None = None,
        sheet_file: str | None = None,
    ) -> str:
        """List all schematic symbols, optionally from a child sheet."""
        target = dependencies.resolve_target(sheet=sheet, sheet_file=sheet_file)
        return service.symbols(target.path)

    @mcp.tool()
    def sch_get_wires(
        sheet: str | None = None,
        sheet_file: str | None = None,
    ) -> str:
        """List all wires in the schematic, optionally from a child sheet."""
        target = dependencies.resolve_target(sheet=sheet, sheet_file=sheet_file)
        return service.wires(target.path)

    @mcp.tool()
    def sch_get_labels(
        sheet: str | None = None,
        sheet_file: str | None = None,
    ) -> str:
        """List all labels in the schematic, optionally from a child sheet."""
        target = dependencies.resolve_target(sheet=sheet, sheet_file=sheet_file)
        return service.labels(target.path)

    @mcp.tool()
    def sch_get_net_names(
        sheet: str | None = None,
        sheet_file: str | None = None,
    ) -> str:
        """List unique net names derived from labels, optionally from a child sheet."""
        target = dependencies.resolve_target(sheet=sheet, sheet_file=sheet_file)
        return service.net_names(target.path)

    @mcp.tool()
    @headless_compatible
    def sch_get_population_status(
        reference: str | None = None,
        sheet: str | None = None,
    ) -> str:
        """Report native KiCad Populate/DNP status for schematic components.

        Returns each placed component's ``populated``/``dnp``/``in_bom`` state
        and any recorded DNP reason. Pass ``reference`` to inspect a single part
        or ``sheet`` to scope the scan to one schematic file.
        """
        return service.population_status(reference=reference, sheet=sheet)

    @mcp.tool()
    def sch_get_pin_positions(
        library: str,
        symbol_name: str,
        x_mm: float,
        y_mm: float,
        rotation: int = 0,
        unit: int = 1,
    ) -> str:
        """Calculate absolute pin positions for a given symbol placement."""
        return service.pin_positions(
            library,
            symbol_name,
            x_mm,
            y_mm,
            rotation,
            unit,
        )

    @mcp.tool()
    def sch_check_power_flags() -> str:
        """Check whether common power nets appear to be flagged."""
        return service.power_flags(dependencies.active_schematic_file())

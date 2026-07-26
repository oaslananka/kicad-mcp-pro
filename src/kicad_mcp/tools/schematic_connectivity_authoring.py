"""Thin FastMCP adapter for schematic connectivity authoring."""

# pyright: reportUnusedFunction=false

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from mcp.server.fastmcp import FastMCP

from ..schematic.connectivity_authoring import SchematicConnectivityAuthoringService
from .metadata import headless_compatible


@dataclass(frozen=True)
class SchematicConnectivityAuthoringDependencies:
    """Connectivity-authoring service injected by the schematic composition root."""

    service: SchematicConnectivityAuthoringService


def register(mcp: FastMCP, dependencies: SchematicConnectivityAuthoringDependencies) -> None:
    """Register schematic connectivity-authoring tools."""
    service = dependencies.service

    @mcp.tool()
    def sch_add_pin_labels(
        connections: list[dict[str, Any]],
        stub_mm: float = 5.08,
        global_labels: bool = True,
        sheet: str | None = None,
        sheet_file: str | None = None,
    ) -> str:
        """Connect placed-symbol pins to nets with a short outward wire stub plus a
        terminal placed clear of the symbol body (avoids label-on-pin overlap).

        Each connection is ``{"reference": "U3", "pin": "VIN" | "5", "net":
        "5V_SYS"}``; the pin may be a number or a name. The stub direction is
        derived from the symbol edge the pin sits on, so the terminal lands outside
        the symbol and reads outward. Power nets get conventional power symbols;
        other nets get labels. Pins that share a ``net`` are joined by their
        common terminal name. This is the clean alternative to placing bare
        labels directly on pins.
        """
        return service.add_pin_labels(
            connections=connections,
            stub_mm=stub_mm,
            global_labels=global_labels,
            sheet=sheet,
            sheet_file=sheet_file,
        )

    @mcp.tool()
    def sch_route_wire_between_pins(
        ref1: str,
        pin1: str,
        ref2: str,
        pin2: str,
        snap_to_grid: bool = True,
    ) -> str:
        """Route deterministic Manhattan wire segments between two placed symbol pins."""
        return service.route_wire_between_pins(
            ref1=ref1,
            pin1=pin1,
            ref2=ref2,
            pin2=pin2,
            snap_to_grid=snap_to_grid,
        )

    @mcp.tool()
    @headless_compatible
    def sch_add_missing_junctions() -> str:
        """Insert missing schematic junctions at T-intersection wire endpoints."""
        return service.add_missing_junctions()

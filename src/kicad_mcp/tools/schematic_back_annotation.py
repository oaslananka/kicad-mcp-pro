"""Thin FastMCP adapters for schematic settings and swap intents."""

from __future__ import annotations

from dataclasses import dataclass

from mcp.server.fastmcp import FastMCP

from ..schematic.back_annotation import SchematicBackAnnotationService
from .metadata import headless_compatible


@dataclass(frozen=True)
class SchematicBackAnnotationDependencies:
    """Back-annotation service injected by the schematic composition root."""

    service: SchematicBackAnnotationService


def register(mcp: FastMCP, dependencies: SchematicBackAnnotationDependencies) -> None:
    """Register schematic settings and deferred swap-intent tools."""
    service = dependencies.service

    @mcp.tool()
    @headless_compatible
    def sch_set_hop_over(enabled: bool = True) -> str:
        """Toggle KiCad 10 hop-over display in the active project settings."""
        return service.set_hop_over(enabled)

    @mcp.tool()
    @headless_compatible
    def sch_list_swappable_pins(component_ref: str) -> str:
        """List candidate pins and units that can participate in a swap workflow."""
        return service.list_swappable_pins(component_ref)

    @mcp.tool()
    @headless_compatible
    def sch_swap_pins(component_ref: str, pin_a: str, pin_b: str) -> str:
        """Record a pin-swap back-annotation intent for a component."""
        return service.swap_pins(component_ref, pin_a, pin_b)

    @mcp.tool()
    @headless_compatible
    def sch_swap_gates(component_ref: str, gate_a: int, gate_b: int) -> str:
        """Record a gate-swap back-annotation intent for a multi-unit component."""
        return service.swap_gates(component_ref, gate_a, gate_b)

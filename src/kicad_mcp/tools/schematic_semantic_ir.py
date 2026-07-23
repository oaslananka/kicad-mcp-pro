"""Thin FastMCP adapter for semantic schematic IR summaries."""

# pyright: reportUnusedFunction=false

from __future__ import annotations

from dataclasses import dataclass

from mcp.server.fastmcp import FastMCP

from ..schematic.semantic_ir import SchematicSemanticIRService
from ..utils.cache import ttl_cache
from .metadata import headless_compatible


@dataclass(frozen=True)
class SchematicSemanticIRDependencies:
    """Semantic-IR service injected by the schematic composition root."""

    service: SchematicSemanticIRService


def register(mcp: FastMCP, dependencies: SchematicSemanticIRDependencies) -> None:
    """Register semantic circuit IR tools."""
    service = dependencies.service

    @mcp.tool()
    @headless_compatible
    @ttl_cache(ttl_seconds=10)
    def sch_get_circuit_ir() -> str:
        """Return the semantic circuit IR for the active schematic.

        The IR decouples 'what the circuit is' (components, nets, pin
        roles, power domains, interfaces) from 'how KiCad stores it'
        (geometry, UUIDs, file format).  Wiring is expressed in terms
        of pin names and roles, not coordinates.

        The output is a structured text summary of the IR.
        """
        return service.get_summary()

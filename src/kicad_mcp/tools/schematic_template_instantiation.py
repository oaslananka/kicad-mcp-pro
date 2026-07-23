"""Thin FastMCP adapter for schematic template instantiation."""

# pyright: reportUnusedFunction=false

from __future__ import annotations

from dataclasses import dataclass

from mcp.server.fastmcp import FastMCP

from ..schematic.template_instantiation import SchematicTemplateInstantiationService
from .metadata import headless_compatible


@dataclass(frozen=True)
class SchematicTemplateInstantiationDependencies:
    """Template-instantiation service injected by the schematic composition root."""

    service: SchematicTemplateInstantiationService


def register(
    mcp: FastMCP,
    dependencies: SchematicTemplateInstantiationDependencies,
) -> None:
    """Register bundled subcircuit template instantiation tools."""
    service = dependencies.service

    @mcp.tool()
    @headless_compatible
    def sch_instantiate_template(
        template_name: str,
        prefix: str = "",
        params: dict[str, object] | None = None,
    ) -> str:
        """Instantiate a subcircuit template — returns a structured action plan.

        This tool returns a structured plan describing the symbols, connections,
        and part-search steps needed to add the subcircuit to the schematic.
        It does NOT directly edit the schematic (use the plan as a guide for
        calling sch_add_symbol, sch_add_wire, lib_recommend_part, etc.).

        Args:
            template_name: Template name (from sch_list_templates()).
            prefix: Reference prefix applied to all template refs (e.g. ``"PWR_"``
                produces ``PWR_U1``, ``PWR_L1``, etc.).
            params: Dict of parameter overrides (e.g. ``{"vout_v": 5.0}``).

        Returns:
            Step-by-step instantiation plan in markdown format.
        """
        return service.instantiate(template_name, prefix, params)

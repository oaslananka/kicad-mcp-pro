"""Thin FastMCP adapters for the schematic template catalog."""

# pyright: reportUnusedFunction=false

from __future__ import annotations

from dataclasses import dataclass

from mcp.server.fastmcp import FastMCP

from ..schematic.template_catalog import SchematicTemplateCatalogService
from .metadata import headless_compatible


@dataclass(frozen=True)
class SchematicTemplateCatalogDependencies:
    """Template-catalog service injected by the schematic composition root."""

    service: SchematicTemplateCatalogService


def register(mcp: FastMCP, dependencies: SchematicTemplateCatalogDependencies) -> None:
    """Register bundled subcircuit template inspection tools."""
    service = dependencies.service

    @mcp.tool()
    @headless_compatible
    def sch_list_templates() -> str:
        """List all available reference subcircuit templates.

        Templates are pre-wired subcircuit blueprints for common building blocks
        (buck converter, LDO, USB Type-C, MCU decoupling, Ethernet with magnetics).

        Call sch_get_template_info() for full parameter and placement details,
        then sch_instantiate_template() to add the subcircuit to the schematic.
        """
        return service.list_templates()

    @mcp.tool()
    @headless_compatible
    def sch_get_template_info(template_name: str) -> str:
        """Return full details for a subcircuit template.

        Args:
            template_name: Template name as returned by sch_list_templates()
                (e.g. ``"buck_converter_generic"``).

        Returns:
            Structured template description including parameters, symbols,
            nets, and placement hints.
        """
        return service.template_info(template_name)

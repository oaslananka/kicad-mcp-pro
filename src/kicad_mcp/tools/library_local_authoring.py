"""FastMCP adapter for local library authoring."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from mcp.server.fastmcp import FastMCP

from .metadata import headless_compatible


class LibraryLocalAuthoringServiceProtocol(Protocol):
    def assign_footprint(self, reference: str, library: str, footprint: str) -> str: ...

    def create_custom_symbol(self, name: str, pins: list[dict[str, Any]]) -> str: ...


@dataclass(frozen=True, slots=True)
class LibraryLocalAuthoringDependencies:
    service: LibraryLocalAuthoringServiceProtocol


def register(mcp: FastMCP, deps: LibraryLocalAuthoringDependencies) -> None:
    """Register local library-authoring tools."""

    @mcp.tool()
    @headless_compatible
    def lib_assign_footprint(reference: str, library: str, footprint: str) -> str:
        """Assign a footprint property to a schematic symbol."""
        return deps.service.assign_footprint(reference, library, footprint)

    @mcp.tool()
    @headless_compatible
    def lib_create_custom_symbol(name: str, pins: list[dict[str, Any]]) -> str:
        """Create a simple custom symbol in the active project directory."""
        return deps.service.create_custom_symbol(name, pins)

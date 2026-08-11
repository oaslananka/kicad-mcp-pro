"""FastMCP adapter for library datasheet lookup."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from mcp.server.fastmcp import FastMCP

from .metadata import headless_compatible


class LibraryDatasheetServiceProtocol(Protocol):
    def get_datasheet_url(self, library: str, symbol_name: str) -> str: ...


@dataclass(frozen=True, slots=True)
class LibraryDatasheetDependencies:
    service: LibraryDatasheetServiceProtocol


def register(mcp: FastMCP, deps: LibraryDatasheetDependencies) -> None:
    """Register the library datasheet tool."""

    @mcp.tool()
    @headless_compatible
    def lib_get_datasheet_url(library: str, symbol_name: str) -> str:
        """Return a datasheet URL from the symbol library when available."""
        return deps.service.get_datasheet_url(library, symbol_name)

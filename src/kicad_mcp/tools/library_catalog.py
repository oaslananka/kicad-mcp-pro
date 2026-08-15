"""Thin FastMCP adapter for symbol and footprint catalog tools."""

# pyright: reportUnusedFunction=false

from __future__ import annotations

from dataclasses import dataclass

from mcp.server.fastmcp import FastMCP

from ..library.catalog import LibraryCatalogService
from ..utils.cache import ttl_cache
from .metadata import headless_compatible


@dataclass(frozen=True)
class LibraryCatalogDependencies:
    """Dependencies for the library catalog adapter."""

    service: LibraryCatalogService


def register(mcp: FastMCP, dependencies: LibraryCatalogDependencies) -> None:
    """Register symbol and footprint catalog tools."""
    service = dependencies.service

    @mcp.tool()
    @headless_compatible
    def lib_list_libraries() -> str:
        """List configured symbol and footprint libraries."""
        return service.list_libraries()

    @mcp.tool()
    @headless_compatible
    @ttl_cache(ttl_seconds=60)
    def lib_search_symbols(
        query: str,
        library_filter: str = "",
        page: int = 1,
        page_size: int = 50,
    ) -> str:
        """Search symbol libraries by name, description, or keywords.

        The query is split into whitespace-separated terms. A symbol matches when
        EVERY term is found (case-insensitive) in any of its name, description, or
        keywords (AND across terms, OR across fields). A single-term query behaves
        as a plain case-insensitive substring match.

        Parameters
        ----------
        query : str
            Search terms. Multiple whitespace-separated terms are matched with AND
            semantics; a single term is a case-insensitive substring match.
        library_filter : str
            Optional library name to narrow the search.
        page : int
            Page number (1-based). Default 1.
        page_size : int
            Results per page. Default 50, max 500.
        """
        return service.search_symbols(query, library_filter, page, page_size)

    @mcp.tool()
    @headless_compatible
    def lib_get_symbol_info(library: str, symbol_name: str) -> str:
        """Return details for a single symbol."""
        return service.get_symbol_info(library, symbol_name)

    @mcp.tool()
    @headless_compatible
    def lib_search_footprints(
        query: str,
        library_filter: str = "",
        page: int = 1,
        page_size: int = 50,
    ) -> str:
        """Search footprint libraries by footprint name.

        Parameters
        ----------
        query : str
            Search term (case-insensitive substring match).
        library_filter : str
            Optional library name to narrow the search.
        page : int
            Page number (1-based). Default 1.
        page_size : int
            Results per page. Default 50, max 500.
        """
        return service.search_footprints(query, library_filter, page, page_size)

    @mcp.tool()
    @headless_compatible
    def lib_list_footprints(library: str) -> str:
        """List footprints in a specific library."""
        return service.list_footprints(library)

    @mcp.tool()
    @headless_compatible
    def lib_rebuild_index() -> str:
        """Rebuild the in-memory symbol search index."""
        return service.rebuild_index()

    @mcp.tool()
    @headless_compatible
    def lib_get_footprint_info(library: str, footprint: str) -> str:
        """Return details for a single footprint."""
        return service.get_footprint_info(library, footprint)

    @mcp.tool()
    @headless_compatible
    def lib_get_footprint_3d_model(library: str, footprint: str) -> str:
        """Return the configured 3D model path for a footprint."""
        return service.get_footprint_3d_model(library, footprint)

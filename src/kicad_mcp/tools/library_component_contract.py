"""Thin FastMCP adapter for placed-component contract verification."""

# pyright: reportUnusedFunction=false

from __future__ import annotations

from dataclasses import dataclass

from mcp.server.fastmcp import FastMCP

from ..library.component_contract import LibraryComponentContractService
from .metadata import headless_compatible


@dataclass(frozen=True)
class LibraryComponentContractDependencies:
    """Dependencies for the library component-contract adapter."""

    service: LibraryComponentContractService


def register(mcp: FastMCP, dependencies: LibraryComponentContractDependencies) -> None:
    """Register placed-component contract verification."""
    service = dependencies.service

    @mcp.tool()
    @headless_compatible
    def lib_verify_component_contract(reference: str) -> str:
        """Verify a placed component's symbol, footprint, and pins actually match.

        For the given schematic reference designator this checks, entirely from
        local project files (no network access):

        - symbol pin count vs footprint connectable pad count
        - pin numbers vs pad numbers
        - footprint courtyard / fabrication / silkscreen completeness
        - 3D model presence (advisory)
        - datasheet evidence (advisory; never auto-filled)

        Returns a JSON object with a ``status`` of PASS / WARN / FAIL and a list
        of per-check ``findings``. FAIL marks a structural contract violation,
        WARN marks a quality/completeness smell, and INFO is advisory evidence
        that never changes the overall status."""
        return service.verify(reference)

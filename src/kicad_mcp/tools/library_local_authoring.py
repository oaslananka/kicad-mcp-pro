"""FastMCP adapter for local library authoring."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from mcp.server.fastmcp import FastMCP

from .metadata import headless_compatible


class LibraryLocalAuthoringServiceProtocol(Protocol):
    def assign_footprint(self, reference: str, library: str, footprint: str) -> str: ...

    def create_custom_symbol(self, name: str, pins: list[dict[str, Any]]) -> str: ...

    def generate_symbol_from_pintable(
        self,
        name: str,
        pins: list[dict[str, Any]],
        reference_prefix: str = "U",
        description: str = "",
        datasheet: str = "",
        footprint_hint: str = "",
        output_path: str = "",
    ) -> str: ...


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


def register_pin_table_generator(mcp: FastMCP, deps: LibraryLocalAuthoringDependencies) -> None:
    """Register the pin-table-driven symbol generator at its legacy position."""

    @mcp.tool()
    @headless_compatible
    def lib_generate_symbol_from_pintable(
        name: str,
        pins: list[dict[str, Any]],
        reference_prefix: str = "U",
        description: str = "",
        datasheet: str = "",
        footprint_hint: str = "",
        output_path: str = "",
    ) -> str:
        """Generate a KiCad symbol (.kicad_sym) from a pin table and save it.

        Each pin dict must contain:
            ``number`` (str | int), ``name`` (str).
        Optional per-pin keys:
            ``pin_type`` (input/output/bidirectional/passive/power_in/power_out/…),
            ``side`` (left/right/top/bottom), ``unit`` (int ≥ 1).

        Args:
            name: Symbol name, used as both the library entry and the default value.
            pins: List of pin specification dicts.
            reference_prefix: Ref-des prefix (U, J, Q, R, …).
            description: Short human description.
            datasheet: Datasheet URL or path.
            footprint_hint: Default footprint (e.g. "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm").
            output_path: Optional relative path inside output_dir. Defaults to
                ``symbols/<name>.kicad_sym``.

        Returns:
            Confirmation with the saved file path, or an error message.
        """
        return deps.service.generate_symbol_from_pintable(
            name,
            pins,
            reference_prefix,
            description,
            datasheet,
            footprint_hint,
            output_path,
        )

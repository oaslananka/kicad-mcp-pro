"""Thin FastMCP adapters for board statistics export tools."""

# pyright: reportUnusedFunction=false

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from mcp.server.fastmcp import FastMCP

from .metadata import headless_compatible


class BoardStatsService(Protocol):
    """Minimal service contract required by the board statistics adapter."""

    def get_board_stats(self) -> str: ...

    def export_board_stats(self, output_name: str | None = None) -> str: ...


@dataclass(frozen=True)
class ExportBoardStatsDependencies:
    """Board statistics dependencies injected by the export composition root."""

    service: BoardStatsService


def register(
    mcp: FastMCP,
    dependencies: ExportBoardStatsDependencies,
    *,
    include_preview: bool = True,
    include_json: bool = True,
) -> None:
    """Register the selected board statistics export tools."""
    service = dependencies.service

    if include_preview:

        @mcp.tool()
        @headless_compatible
        def get_board_stats() -> str:
            """Export board statistics and return a readable preview."""
            return service.get_board_stats()

    if include_json:

        @mcp.tool()
        @headless_compatible
        def pcb_export_stats(output_name: str | None = None) -> str:
            """Export board statistics (net count, component count, layer count, etc.)
            via the KiCad CLI ``pcb export stats`` command.

            Parameters
            ----------
            output_name : str | None
                Optional output file name (saved under the project output directory).
                Defaults to ``board_stats.json``.
            """
            return service.export_board_stats(output_name)

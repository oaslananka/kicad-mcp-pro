"""Thin FastMCP adapters for PCB board overview and collection inspection."""

# pyright: reportUnusedFunction=false

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from mcp.server.fastmcp import FastMCP

from ..models.verdict import VerdictReport
from ..utils.cache import ttl_cache
from .metadata import headless_compatible


class BoardInspectionService(Protocol):
    """Minimal board-inspection service contract required by the adapter."""

    def get_board_summary(self) -> VerdictReport: ...

    def get_tracks(
        self,
        *,
        page: int = 1,
        page_size: int = 100,
        filter_layer: str = "",
        filter_net: str = "",
    ) -> str: ...

    def get_vias(self) -> str: ...

    def get_footprints(
        self,
        *,
        page: int = 1,
        page_size: int = 50,
        filter_layer: str = "",
    ) -> str: ...


@dataclass(frozen=True)
class PcbBoardInspectionDependencies:
    """Board-inspection dependencies injected by the composition root."""

    service: BoardInspectionService


def register(mcp: FastMCP, dependencies: PcbBoardInspectionDependencies) -> None:
    """Register PCB board overview and collection inspection tools."""
    service = dependencies.service

    @mcp.tool()
    @headless_compatible
    @ttl_cache(ttl_seconds=5)
    def pcb_get_board_summary() -> VerdictReport:
        """Summarize the current board."""
        return service.get_board_summary()

    @mcp.tool()
    @headless_compatible
    def pcb_get_tracks(
        page: int = 1,
        page_size: int = 100,
        filter_layer: str = "",
        filter_net: str = "",
    ) -> str:
        """List board tracks."""
        return service.get_tracks(
            page=page,
            page_size=page_size,
            filter_layer=filter_layer,
            filter_net=filter_net,
        )

    @mcp.tool()
    @headless_compatible
    def pcb_get_vias() -> str:
        """List board vias."""
        return service.get_vias()

    @mcp.tool()
    @headless_compatible
    def pcb_get_footprints(
        page: int = 1,
        page_size: int = 50,
        filter_layer: str = "",
    ) -> str:
        """List board footprints."""
        return service.get_footprints(
            page=page,
            page_size=page_size,
            filter_layer=filter_layer,
        )

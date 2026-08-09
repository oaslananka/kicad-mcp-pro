"""Thin FastMCP adapter for Gerber export."""

# pyright: reportUnusedFunction=false

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Protocol

import anyio
from mcp.server.fastmcp import Context, FastMCP

from .metadata import headless_compatible


class GerberService(Protocol):
    """Minimal service contract required by the Gerber adapter."""

    def export(
        self,
        output_subdir: str = "gerber",
        layers: list[str] | None = None,
        variant_name: str | None = None,
    ) -> str: ...


type ReportProgress = Callable[[Context[Any, Any, Any] | None, float, float, str], Awaitable[None]]


@dataclass(frozen=True)
class ExportGerberDependencies:
    """Gerber-export dependencies injected by the export composition root."""

    service: GerberService
    add_low_level_notice: Callable[[str], str]
    report_progress: ReportProgress


def register(mcp: FastMCP, dependencies: ExportGerberDependencies) -> None:
    """Register the Gerber export tool."""
    service = dependencies.service
    add_low_level_notice = dependencies.add_low_level_notice
    report_progress = dependencies.report_progress

    @mcp.tool()
    @headless_compatible
    async def export_gerber(
        output_subdir: str = "gerber",
        layers: list[str] | None = None,
        ctx: Context[Any, Any, Any] | None = None,
    ) -> str:
        """Export Gerber manufacturing files."""
        await report_progress(ctx, 5, 100, "Starting Gerber export...")
        result = await anyio.to_thread.run_sync(
            lambda: add_low_level_notice(service.export(output_subdir, layers))
        )
        await report_progress(ctx, 100, 100, "Gerber export complete.")
        return result

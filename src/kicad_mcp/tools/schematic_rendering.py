"""Thin FastMCP adapter for schematic rendering and live preview."""

# pyright: reportUnusedFunction=false

from __future__ import annotations

from dataclasses import dataclass

from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult

from ..mcp_media import image_tool_result, text_tool_result
from ..schematic.rendering import SchematicRenderingResponse, SchematicRenderingService
from .metadata import headless_compatible


@dataclass(frozen=True)
class SchematicRenderingDependencies:
    """Rendering service injected by the schematic composition root."""

    service: SchematicRenderingService


def _tool_result(response: SchematicRenderingResponse) -> CallToolResult:
    if response.image_path is not None:
        return image_tool_result(response.image_path, response.metadata or {})
    return text_tool_result(response.text or "", metadata=response.metadata)


def register(mcp: FastMCP, dependencies: SchematicRenderingDependencies) -> None:
    """Register schematic rendering and live-preview tools."""
    service = dependencies.service

    @mcp.tool()
    @headless_compatible
    def sch_live_preview(
        sheet: str | None = None,
        sheet_file: str | None = None,
        include_child_sheets: bool = True,
        debounce_ms: int = 750,
        render: bool = True,
        reload: bool = False,
        force: bool = False,
        crop_to_content: bool = True,
        dpi: int = 200,
        include_title_block: bool = True,
        output_file: str | None = None,
    ) -> CallToolResult:
        """Poll a safe live schematic preview state and refresh rendered output on changes.

        This is an opt-in polling watcher for agents and companion-plugin flows. It
        records the current schematic file signature, debounces rapid writes, then
        refreshes a PNG preview when the watched files are stable. KiCad GUI reload
        is deliberately opt-in via ``reload=True`` because the tool cannot reliably
        prove that the user has no unsaved GUI edits.
        """
        return _tool_result(
            service.live_preview(
                sheet=sheet,
                sheet_file=sheet_file,
                include_child_sheets=include_child_sheets,
                debounce_ms=debounce_ms,
                render=render,
                reload=reload,
                force=force,
                crop_to_content=crop_to_content,
                dpi=dpi,
                include_title_block=include_title_block,
                output_file=output_file,
            )
        )

    @mcp.tool()
    @headless_compatible
    def sch_render_png(
        sheet: str | None = None,
        sheet_file: str | None = None,
        crop_to_content: bool = True,
        dpi: int = 200,
        include_title_block: bool = True,
        output_file: str | None = None,
    ) -> CallToolResult:
        """Render a schematic sheet to PNG for visual self-checks.

        Uses headless ``kicad-cli sch export svg`` followed by SVG-to-PNG
        conversion. Empty sheets return ``status=empty_sheet`` instead of a
        misleading blank image.
        """
        return _tool_result(
            service.render_png(
                sheet=sheet,
                sheet_file=sheet_file,
                crop_to_content=crop_to_content,
                dpi=dpi,
                include_title_block=include_title_block,
                output_file=output_file,
            )
        )

    @mcp.tool()
    @headless_compatible
    def sch_render_visual_diff(
        sheet: str | None = None,
        sheet_file: str | None = None,
        dpi: int = 200,
        include_title_block: bool = True,
        output_file: str | None = None,
    ) -> CallToolResult:
        """Render the exact visual delta produced by the last schematic mutation.

        The red pixels are the aligned before/after image difference. Metadata lists
        every changed symbol, label/net, wire, bus, junction, or document object.
        """
        return _tool_result(
            service.render_visual_diff(
                sheet=sheet,
                sheet_file=sheet_file,
                dpi=dpi,
                include_title_block=include_title_block,
                output_file=output_file,
            )
        )

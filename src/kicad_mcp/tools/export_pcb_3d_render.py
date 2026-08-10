"""Thin FastMCP adapter for PCB 3D render export."""

# pyright: reportUnusedFunction=false

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass

from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult

from ..export.pcb_3d_render import ExportPcb3dRenderService
from ..mcp_media import image_tool_result, text_tool_result
from .metadata import headless_compatible


@dataclass(frozen=True)
class ExportPcb3dRenderDependencies:
    """PCB 3D render service and public low-level export notice."""

    service: ExportPcb3dRenderService
    add_low_level_notice: Callable[[str], str]


def register(mcp: FastMCP, dependencies: ExportPcb3dRenderDependencies) -> None:
    """Register the PCB 3D render export tool."""
    service = dependencies.service
    add_low_level_notice = dependencies.add_low_level_notice

    @mcp.tool()
    @headless_compatible
    def export_3d_render(
        output_file: str = "render.png",
        side: str = "top",
        zoom: float = 1.0,
        width: int | None = None,
        height: int | None = None,
        quality: float | None = None,
        preset: str | None = None,
        use_board_stackup_colors: bool = False,
        floor: bool = True,
        perspective: bool = True,
        pan_x: float | None = None,
        pan_y: float | None = None,
        rotate_x: float | None = None,
        rotate_y: float | None = None,
        rotate_z: float | None = None,
        light_top: float | None = None,
        light_bottom: float | None = None,
        light_side: float | None = None,
        light_camera: float | None = None,
        light_side_elevation: float | None = None,
    ) -> CallToolResult:
        """Render a 3D view of the active PCB board to a PNG image.

        Parameters
        ----------
        output_file : str
            Output file name (PNG or JPG). Defaults to ``render.png``.
        side : str
            View direction: ``top``, ``bottom``, ``front``, ``back``, ``left``, ``right``.
        zoom : float
            Camera zoom factor (0.05–20.0).
        width, height : int | None
            Output image dimensions in pixels.
        quality : float | None
            Rendering quality (0.0–1.0).
        preset : str | None
            Render preset name (e.g. ``photo``, ``standard``).
        use_board_stackup_colors : bool
            Use the board stackup-defined colors.
        floor : bool
            Show the reflective floor. Default True.
        perspective : bool
            Perspective projection. Set False for orthographic.
        pan_x, pan_y : float | None
            Camera pan offset in mm.
        rotate_x, rotate_y, rotate_z : float | None
            Camera rotation in degrees.
        light_top, light_bottom, light_side, light_camera : float | None
            Light intensity for each direction (0.0–1.0).
        light_side_elevation : float | None
            Side light elevation angle in degrees.
        """
        response = service.render(
            output_file=output_file,
            side=side,
            zoom=zoom,
            width=width,
            height=height,
            quality=quality,
            preset=preset,
            use_board_stackup_colors=use_board_stackup_colors,
            floor=floor,
            perspective=perspective,
            pan_x=pan_x,
            pan_y=pan_y,
            rotate_x=rotate_x,
            rotate_y=rotate_y,
            rotate_z=rotate_z,
            light_top=light_top,
            light_bottom=light_bottom,
            light_side=light_side,
            light_camera=light_camera,
            light_side_elevation=light_side_elevation,
        )
        if response.text is not None:
            return text_tool_result(add_low_level_notice(response.text))

        if response.image_path is None or response.summary is None:
            raise RuntimeError("PCB 3D render service returned an incomplete image response.")
        metadata = {
            "status": "ok",
            "png_path": str(response.image_path),
            "side": side,
            "zoom": zoom,
            "width": width,
            "height": height,
            "preset": preset,
        }
        return image_tool_result(
            response.image_path,
            metadata,
            text=add_low_level_notice(
                f"{response.summary}\n{json.dumps(metadata, indent=2)}",
            ),
        )

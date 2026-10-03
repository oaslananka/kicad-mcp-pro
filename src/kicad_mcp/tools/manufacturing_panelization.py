"""Thin FastMCP adapter for manufacturing panelization."""

# pyright: reportUnusedFunction=false

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass

from mcp.server.mcpserver import MCPServer as FastMCP

from ..config import get_config
from ..manufacturing.panelization import PanelizationService
from .metadata import headless_compatible


@dataclass(frozen=True)
class ManufacturingPanelizationDependencies:
    service: PanelizationService


def _default_dependencies() -> ManufacturingPanelizationDependencies:
    return ManufacturingPanelizationDependencies(
        service=PanelizationService(
            kikit_available=lambda: shutil.which("kikit") is not None,
            get_pcb_file=lambda: get_config().pcb_file,
            ensure_output_dir=lambda name: get_config().ensure_output_dir(name),
            resolve_output_path=lambda path: get_config().resolve_within_project(path),
            run_command=lambda cmd: subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                errors="replace",
                timeout=120,
            ),
        )
    )


def register(
    mcp: FastMCP,
    dependencies: ManufacturingPanelizationDependencies | None = None,
) -> None:
    """Register the manufacturing panelization tool."""
    service = (dependencies or _default_dependencies()).service

    @mcp.tool()
    @headless_compatible
    def mfg_panelize(
        layout: str = "grid",
        rows: int = 2,
        cols: int = 2,
        spacing_mm: float = 2.0,
        frame_width_mm: float = 5.0,
        output_path: str = "",
        dry_run: bool = True,
        confirm: bool = False,
    ) -> str:
        """Panelize the active PCB using KiKit.

        Creates a panel of multiple boards for efficient PCB fabrication.
        Requires ``kikit`` to be installed (``pip install kikit``).

        Args:
            layout: Panel layout type: ``"grid"`` (rectangular array),
                ``"mousebites"`` (tab+mousebite breakaway), or ``"vcut"`` (V-cut scoring).
            rows: Number of board rows in the panel.
            cols: Number of board columns in the panel.
            spacing_mm: Gap between boards in mm.
            frame_width_mm: Panel frame/rail width in mm.
            output_path: Optional output file path (relative to output_dir).
                Defaults to ``panel/<boardname>_panel_<rows>x<cols>.kicad_pcb``.
            dry_run: If True, return the planned command and output path without writing files.
            confirm: Must be True when ``dry_run`` is False to run KiKit.

        Returns:
            Confirmation with the panel file path, or an error message.
        """
        return service.panelize(
            layout=layout,
            rows=rows,
            cols=cols,
            spacing_mm=spacing_mm,
            frame_width_mm=frame_width_mm,
            output_path=output_path,
            dry_run=dry_run,
            confirm=confirm,
        )

"""Prompt templates for common KiCad workflows."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP
from mcp.types import TextContent


def register(mcp: FastMCP) -> None:
    """Register reusable workflow prompts."""

    @mcp.prompt()
    def first_pcb(
        component_count: str = "10",
        board_size_mm: str = "50x50",
        layers: str = "2",
    ) -> list[TextContent]:
        """Guide an agent through a first-board workflow."""
        text = f"""
Design a new KiCad PCB with approximately {component_count} components, a board size of
{board_size_mm} mm, and {layers} copper layers.

Workflow:
1. Call `kicad_get_version()`.
2. Call `kicad_set_project()` or `kicad_create_new_project()`.
3. Review `kicad://project/info` and `kicad://board/summary`.
4. Define the outline with `pcb_set_board_outline()`.
5. Populate the schematic using the schematic and library tools.
6. Run `run_erc()` and fix issues before layout.
7. Route with PCB tools.
8. Run `run_drc()` and `check_design_for_manufacture()`.
9. Export a manufacturing package.
""".strip()
        return [TextContent(type="text", text=text)]

    @mcp.prompt()
    def schematic_to_pcb() -> list[TextContent]:
        """Guide an agent from schematic capture to PCB layout."""
        text = """
Move a design from schematic capture to PCB layout.

1. Inspect the active project and schematic.
2. Add or update symbols, labels, buses, and power flags.
3. Run ERC and power checks.
4. Export the netlist.
5. Inspect footprints and assign missing ones.
6. Move footprints, route key nets, and refill zones.
7. Run DRC and compare PCB versus schematic footprints.
""".strip()
        return [TextContent(type="text", text=text)]

    @mcp.prompt()
    def manufacturing_export() -> list[TextContent]:
        """Checklist for manufacturing exports."""
        text = """
Run a manufacturing readiness pass.

1. `run_drc()`
2. `run_erc()`
3. `get_board_stats()`
4. `check_design_for_manufacture()`
5. `export_gerber()`
6. `export_drill()`
7. `export_bom()`
8. `export_pick_and_place()`
9. `export_ipc2581()`
10. `export_manufacturing_package()`
""".strip()
        return [TextContent(type="text", text=text)]

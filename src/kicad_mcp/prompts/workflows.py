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
Run a manufacturing release pass. Treat `export_manufacturing_package()` as a release
step, not a debugging shortcut.

1. `project_quality_gate()`
2. If the gate is not `PASS`, stop and fix the blocking issues first.
3. `pcb_transfer_quality_gate()`
4. `run_drc()`
5. `run_erc()`
6. `get_board_stats()`
7. `check_design_for_manufacture()`
8. Use low-level export tools only for debugging if needed:
   - `export_gerber()`
   - `export_drill()`
   - `export_bom()`
   - `export_pick_and_place()`
   - `export_ipc2581()`
9. Only after a clean gate, call `export_manufacturing_package()`.
""".strip()
        return [TextContent(type="text", text=text)]

    @mcp.prompt()
    def design_review_loop() -> list[TextContent]:
        """Closed-loop inspection workflow driven by quality gates."""
        text = """
Run a closed-loop design review instead of trusting a single build pass.

1. Inspect the current context:
   - `kicad://project/info`
   - `kicad://project/quality_gate`
   - `kicad://project/fix_queue`
   - `kicad://schematic/connectivity`
   - `kicad://board/placement_quality`
   - `project_get_design_intent()`
2. Call the blocking gate tools directly when you need fresh detail:
   - `project_quality_gate()`
   - `schematic_connectivity_gate()`
   - `pcb_transfer_quality_gate()`
   - `pcb_score_placement()`
3. Fix the highest-severity blocking issue first.
4. Re-run the relevant gates after every fix.
5. Repeat until the full project gate is `PASS`.
6. Only then move on to release exports.
""".strip()
        return [TextContent(type="text", text=text)]

    @mcp.prompt()
    def fix_blocking_issues() -> list[TextContent]:
        """Prompt focused on consuming the fix queue and clearing blockers."""
        text = """
Use the project fix queue as the source of truth for what to fix next.

1. Read `kicad://project/fix_queue`.
2. Pick item 1 unless a more severe blocker appears after re-running a gate.
3. Use the suggested tool on that line to inspect or repair the issue.
4. If the blocker is intent-aware, refresh `project_get_design_intent()` or update it with
   `project_set_design_intent()` before moving footprints again.
5. Re-run `project_quality_gate()` after the fix.
6. Stop only when the queue says there are no blocking issues left.
""".strip()
        return [TextContent(type="text", text=text)]

    @mcp.prompt()
    def manufacturing_release_checklist() -> list[TextContent]:
        """Final release checklist for fab-ready handoff."""
        text = """
Treat manufacturing release as a gated handoff.

1. Read `kicad://project/quality_gate`.
2. If the project gate is not `PASS`, stop immediately and clear blockers.
3. Read `kicad://project/fix_queue` to confirm nothing actionable remains.
4. Re-run:
   - `project_quality_gate()`
   - `pcb_transfer_quality_gate()`
   - `run_drc()`
   - `run_erc()`
   - `check_design_for_manufacture()`
5. Use low-level export tools only for debugging artifacts.
6. Release with `export_manufacturing_package()` only after every gate is clean.
""".strip()
        return [TextContent(type="text", text=text)]

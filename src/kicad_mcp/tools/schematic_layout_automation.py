"""Thin FastMCP adapter for schematic layout and readability automation."""

# pyright: reportUnusedFunction=false

from __future__ import annotations

from dataclasses import dataclass

from mcp.server.fastmcp import FastMCP

from ..schematic.layout_automation import SchematicLayoutAutomationService
from .metadata import headless_compatible


@dataclass(frozen=True)
class SchematicLayoutAutomationDependencies:
    """Layout automation service injected by the schematic composition root."""

    service: SchematicLayoutAutomationService


def register(mcp: FastMCP, dependencies: SchematicLayoutAutomationDependencies) -> None:
    """Register schematic layout and readability automation tools."""
    service = dependencies.service

    @mcp.tool()
    def sch_auto_place_symbols(
        symbol_list: list[str] | None = None,
        strategy: str = "cluster",
    ) -> str:
        """Place selected references with a deterministic cluster, linear, star, or grid layout.

        Unlike the legacy behaviour, this version reads all already-placed symbols
        first and avoids placing new symbols on top of them.  Fixed/already-placed
        symbols that are not in ``symbol_list`` are treated as immovable obstacles.
        """
        return service.auto_place_symbols(symbol_list=symbol_list, strategy=strategy)

    @mcp.tool()
    @headless_compatible
    def sch_autoplace_fields(references: list[str] | None = None, dry_run: bool = False) -> str:
        """Reposition symbol Reference/Value text onto the clearest body side.

        Mirrors KiCad's ``autoplace_fields``: for each symbol the visible
        Reference and Value fields are moved to the body side with the most
        clearance, away from pins and neighbouring symbols, so the rendered sheet
        stops stacking text on top of other text. Footprint/Datasheet and hidden
        fields are left untouched. Pass ``references`` to limit the operation to
        specific designators, or ``dry_run`` to preview the count without writing.

        Run this after ``sch_auto_place_symbols`` (or any bulk placement) and use
        ``sch_visual_qa`` to confirm the ``text_overlap`` findings clear.
        """
        return service.autoplace_fields(references=references, dry_run=dry_run)

    @mcp.tool()
    @headless_compatible
    def sch_fix_readability(max_passes: int = 3) -> str:
        """Iteratively fix schematic readability defects until clean or stable.

        Runs the headless ``sch_visual_qa`` checks, then applies the matching
        fixer and re-checks, looping until the sheet passes, no further progress
        is made, or ``max_passes`` is reached:

        - **off-sheet** symbols/labels -> grow the sheet one paper size (A4 -> A3 ...)
        - **text overlap** -> auto-place Reference/Value fields onto clear body sides
        - **symbol-body overlap** -> re-space the symbols on a body-sized grid, but
          ONLY when the sheet has no wires, labels or power symbols (moving a
          connected symbol would break its nets); otherwise it is reported.

        Dense label clusters are reported for manual follow-up (label anchors are
        electrical attachment points and cannot be moved safely). Returns a
        per-pass log with the before/after QA status so the closing state is
        explicit.
        """
        return service.fix_readability(max_passes=max_passes)

    @mcp.tool()
    @headless_compatible
    def sch_auto_place_functional(
        symbol_list: list[str] | None = None,
        anchor_ref: str | list[str] | None = None,
    ) -> str:
        """Place schematic symbols into semantically meaningful zones on the sheet.

        Unlike the basic ``sch_auto_place_symbols`` which uses a plain grid,
        this tool categorises each symbol by its **function** (MCU, connector,
        power IC, sensor, passive, protection …) and places it in the
        corresponding region of the schematic sheet.  The result is a readable,
        professionally structured schematic with logical signal flow
        (connectors on the left, processing in the centre, power/decoupling at
        the bottom).

        Zone layout (column × row, each cell = 25.4 × 17.78 mm)::

            Col →    0-2          3-5          6-8
            Row 0:   connectors   MCU          UI/LED/SW
            Row 3:   power IC     sensors/IC   protection
            Row 5:   power_pass   passives     transistors/filter
            Row 7:   test points  ---          misc

        The actual sheet size is read from the schematic file.  If the symbol
        count would overflow the current sheet, a warning is appended
        recommending ``sch_auto_resize_sheet`` to switch to a larger format
        (A3, A2, …) before re-running this tool.

        Symbols already placed (not in ``symbol_list``) are treated as fixed
        obstacles and will not be overwritten.  Within each zone, symbols are
        arranged in a compact row-major sub-grid.

        Args:
            symbol_list: Optional list of reference designators to place.  If
                omitted, all symbols in the schematic are placed.
            anchor_ref: Optional single reference or list of references to keep
                fixed while re-placing the remaining symbols around them.

        Returns:
            A summary showing how many symbols were placed per functional zone,
            plus an overflow warning if the sheet is too small.
        """
        return service.auto_place_functional(symbol_list=symbol_list, anchor_ref=anchor_ref)

"""Thin FastMCP adapter for schematic circuit compilation."""

# pyright: reportUnusedFunction=false

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from mcp.server.fastmcp import FastMCP

from ..schematic.circuit_compilation import SchematicCircuitCompilationService


@dataclass(frozen=True)
class SchematicCircuitCompilationDependencies:
    """Circuit-compilation service injected by the schematic composition root."""

    service: SchematicCircuitCompilationService


def register(
    mcp: FastMCP,
    dependencies: SchematicCircuitCompilationDependencies,
) -> None:
    """Register schematic circuit-compilation tools."""
    service = dependencies.service

    @mcp.tool()
    def sch_analyze_net_compilation(
        symbols: list[dict[str, Any]] | None = None,
        wires: list[dict[str, Any]] | None = None,
        labels: list[dict[str, Any]] | None = None,
        power_symbols: list[dict[str, Any]] | None = None,
        nets: list[dict[str, Any]] | None = None,
        snap_to_grid: bool = True,
        auto_layout: bool = False,
        unsafe_routed_wires: bool = False,
    ) -> str:
        """Preview how netlist-aware schematic compilation will resolve endpoints and wires.

        Mirrors ``sch_build_circuit``: by default nets resolve to collision-safe
        terminal stubs; pass ``unsafe_routed_wires=True`` to preview routed Manhattan
        wire segments instead.
        """
        return service.analyze(
            symbols=symbols,
            wires=wires,
            labels=labels,
            power_symbols=power_symbols,
            nets=nets,
            snap_to_grid=snap_to_grid,
            auto_layout=auto_layout,
            unsafe_routed_wires=unsafe_routed_wires,
        )

    @mcp.tool()
    def sch_build_circuit(
        symbols: list[dict[str, Any]] | None = None,
        wires: list[dict[str, Any]] | None = None,
        labels: list[dict[str, Any]] | None = None,
        power_symbols: list[dict[str, Any]] | None = None,
        nets: list[dict[str, Any]] | None = None,
        snap_to_grid: bool = True,
        auto_layout: bool = False,
        unsafe_routed_wires: bool = False,
        max_paper: str = "A3",
    ) -> str:
        """Build (overwrite) the active schematic from structured symbol, wire, and label inputs.

        IMPORTANT: This tool **replaces** the entire schematic content.  Any symbols
        already placed in the schematic will be lost.  To add symbols to an existing
        schematic without erasing it use ``sch_add_symbol`` / ``sch_add_wire`` /
        ``sch_add_label`` instead.

        Coordinates are snapped to the 1.27 mm / 50 mil grid by default.  When no coordinates
        are provided for a symbol, set ``auto_layout=True`` so the placement engine
        assigns non-overlapping positions automatically.

        When ``nets`` are provided, the builder is connection-aware. By default it
        uses the **collision-safe** strategy: each pin endpoint gets a short stub plus
        a same-named terminal (a global label for signal nets, a power symbol for
        power nets), so nets connect *by name* and can never short by crossing wire
        geometry.  Nets that cannot resolve to a routable pin endpoint raise a clear
        error (or are surfaced as warnings) instead of silently producing a
        disconnected schematic.

        Each net may set an optional ``scope`` to control the emitted terminal
        label kind: ``"global"`` (default when omitted, connects across the whole
        design), ``"local"`` (sheet-local label), or ``"hierarchical"`` (with an
        optional ``shape`` of input/output/bidirectional for sheet-pin wiring).

        Set ``unsafe_routed_wires=True`` only if you explicitly want routed Manhattan
        wire segments between pins.  That star-routing can cross unrelated pins or
        labels and KiCad will merge them by geometry, so it can introduce silent
        shorts on non-trivial netlists — prefer the default terminal strategy.

        Each symbol may carry an optional ``properties`` mapping (``dict[str, str]``);
        every key/value is written verbatim as an additional schematic symbol field,
        alongside the standard fields — handy for order numbers such as
        ``{"MPN": "...", "Mouser": "...", "LCSC": "..."}`` without a second
        ``sch_update_properties`` pass.  Keys colliding with the standard
        Reference/Value/Footprint/Datasheet fields are ignored in favour of the
        dedicated ``reference``/``value``/``footprint`` inputs (those always win).

        With ``auto_layout=True`` the placement engine grows the sheet up the ISO-A
        ladder (A4 → A3 → A2 → A1 → A0) only as far as ``max_paper`` (default
        ``"A3"``). Once the cap is reached, placement continues on that paper
        instead of selecting a larger page. This limits paper growth but does not
        guarantee that arbitrarily dense inputs fit within the capped page; use
        visual/layout validation or explicit coordinates for dense designs. Pass
        a larger cap (e.g. ``max_paper="A0"``) for the historical largest-paper
        behavior. ``max_paper`` must be one of A4/A3/A2/A1/A0; any other value
        raises ``ValueError``.

        Recommended workflow:
          1. Call ``sch_find_free_placement(count=N)`` to obtain safe coordinates.
          2. Pass those coordinates in the ``symbols`` list.
          3. OR set ``auto_layout=True`` and omit coordinates entirely.
        """
        return service.build(
            symbols=symbols,
            wires=wires,
            labels=labels,
            power_symbols=power_symbols,
            nets=nets,
            snap_to_grid=snap_to_grid,
            auto_layout=auto_layout,
            unsafe_routed_wires=unsafe_routed_wires,
            max_paper=max_paper,
        )

"""FastMCP-independent schematic layout inspection services."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol


class EstimateOccupiedCells(Protocol):
    def __call__(
        self,
        symbols: list[dict[str, Any]],
        cell_w: float,
        cell_h: float,
    ) -> set[tuple[int, int]]: ...


class KeepoutOccupiedCells(Protocol):
    def __call__(
        self,
        keepout_regions: list[tuple[float, float, float, float]],
        *,
        cell_w: float,
        cell_h: float,
    ) -> set[tuple[int, int]]: ...


class NextFreeCell(Protocol):
    def __call__(
        self,
        occupied: set[tuple[int, int]],
        cell_w: float,
        cell_h: float,
    ) -> tuple[float, float]: ...


@dataclass(frozen=True)
class SchematicLayoutInspectionService:
    """Inspect occupied schematic geometry and suggest free placement slots."""

    active_schematic_file: Callable[[], Path]
    parse_schematic: Callable[[Path], dict[str, Any]]
    with_diagnostics: Callable[[str, Path], str]
    symbol_bbox_bounds: Callable[[dict[str, Any]], tuple[float, float, float, float]]
    estimate_occupied_cells: EstimateOccupiedCells
    keepout_occupied_cells: KeepoutOccupiedCells
    next_free_cell: NextFreeCell

    def bounding_boxes(self) -> str:
        sch_file = self.active_schematic_file()
        sch_data = self.parse_schematic(sch_file)
        all_syms = sch_data["symbols"] + sch_data["power_symbols"]

        if not all_syms:
            return self.with_diagnostics(
                "The active schematic contains no symbols.",
                sch_file,
            )

        lines = [
            f"Schematic bounding boxes ({len(all_syms)} symbols):",
            (
                f"{'Ref':<10} {'Value':<16} {'X':>8} {'Y':>8} "
                f"{'X_min':>8} {'Y_min':>8} {'X_max':>8} {'Y_max':>8}"
            ),
            "-" * 76,
        ]
        extents: list[tuple[float, float, float, float]] = []
        for sym in all_syms:
            ref = str(sym.get("reference", "?"))
            val = str(sym.get("value", ""))[:16]
            x = float(sym.get("x", sym.get("x_mm", 0.0)) or 0.0)
            y = float(sym.get("y", sym.get("y_mm", 0.0)) or 0.0)
            x_min, y_min, x_max, y_max = self.symbol_bbox_bounds(sym)
            extents.append((x_min, y_min, x_max, y_max))
            lines.append(
                f"{ref:<10} {val:<16} {x:>8.2f} {y:>8.2f} "
                f"{x_min:>8.2f} {y_min:>8.2f} {x_max:>8.2f} {y_max:>8.2f}"
            )

        lines += [
            "",
            f"Sheet occupied region: X=[{min(item[0] for item in extents):.1f}, "
            f"{max(item[2] for item in extents):.1f}] "
            f"Y=[{min(item[1] for item in extents):.1f}, "
            f"{max(item[3] for item in extents):.1f}] mm",
            "Tip: use sch_find_free_placement to get safe coordinates for new symbols.",
        ]
        return "\n".join(lines)

    def free_placement(
        self,
        count: int,
        cell_width_mm: float,
        cell_height_mm: float,
        keepout_regions: list[tuple[float, float, float, float]] | None,
    ) -> str:
        count = max(1, min(count, 64))
        sch_file = self.active_schematic_file()
        sch_data = self.parse_schematic(sch_file)
        all_syms = sch_data["symbols"] + sch_data["power_symbols"]

        occupied = self.estimate_occupied_cells(all_syms, cell_width_mm, cell_height_mm)
        keepouts = keepout_regions or []
        if keepouts:
            occupied.update(
                self.keepout_occupied_cells(
                    keepouts,
                    cell_w=cell_width_mm,
                    cell_h=cell_height_mm,
                )
            )

        coords: list[tuple[float, float]] = []
        for _ in range(count):
            x, y = self.next_free_cell(occupied, cell_width_mm, cell_height_mm)
            coords.append((round(x, 4), round(y, 4)))

        lines = [
            f"Free placement coordinates ({count} slot(s) requested, "
            f"{len(all_syms)} existing symbol(s) avoided, "
            f"{len(keepouts)} keepout region(s) respected):",
        ]
        for index, (x, y) in enumerate(coords, start=1):
            lines.append(f"  Slot {index}: x_mm={x}, y_mm={y}")
        lines.append("\nPass these coordinates directly to sch_add_symbol(x_mm=..., y_mm=...).")
        return "\n".join(lines)

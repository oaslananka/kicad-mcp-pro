"""FastMCP-independent schematic layout and readability automation."""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol, cast

from ..models.schematic import AutoPlaceSymbolsInput


class ComponentLike(Protocol):
    """Placed component surface required by the layout service."""

    def move(self, x: float, y: float) -> None: ...


class ComponentCollectionLike(Protocol):
    """Component lookup surface required by the layout service."""

    def get(self, reference: str) -> ComponentLike | None: ...


class SchematicLike(Protocol):
    """Loaded schematic surface required by the layout service."""

    @property
    def components(self) -> ComponentCollectionLike: ...

    def save(self, path: Path, *, preserve_format: bool) -> None: ...


class FunctionalDesignIntentLike(Protocol):
    """Design-intent setting consumed by functional placement."""

    @property
    def functional_spacing_mm(self) -> float: ...


FieldMutator = Callable[[str], str]
ParsedSchematic = dict[str, Any]
LayoutStrategy = Literal["cluster", "linear", "star", "grid"]


@dataclass(frozen=True)
class SchematicLayoutAutomationService:
    """Coordinate schematic symbol placement and readability repair."""

    active_schematic_file: Callable[[], Path]
    load_schematic: Callable[[Path], SchematicLike]
    parse_schematic: Callable[[Path], ParsedSchematic]
    with_diagnostics: Callable[[str, Path], str]
    estimate_occupied_cells: Callable[[list[dict[str, Any]]], set[tuple[int, int]]]
    next_free_cell: Callable[..., tuple[float, float]]
    snap_point: Callable[[float, float, bool], tuple[float, float]]
    reload_schematic: Callable[[], str]
    build_autoplace_fields_mutator: Callable[
        [Path, list[str] | None], tuple[FieldMutator, list[str], list[str]]
    ]
    transactional_write_to_schematic_file: Callable[[Path, FieldMutator], object]
    run_visual_qa: Callable[[str], Mapping[str, Any]]
    read_sheet_paper: Callable[[Path], str]
    paper_ladder: tuple[str, ...]
    resize_sheet_apply: Callable[[Path, str], bool]
    schematic_has_connections: Callable[[str], bool]
    respace_symbols_apply: Callable[[Path], list[str]]
    autoplace_fields_apply: Callable[[Path], list[str]]
    load_design_intent: Callable[[], FunctionalDesignIntentLike]
    normalize_anchor_refs: Callable[[str | list[str] | None], list[str]]
    sheet_usable_cols: Callable[[str], int]
    sheet_usable_rows: Callable[[str], int]
    paper_sizes_mm: Mapping[str, tuple[float, float]]
    classify_symbol: Callable[..., str]
    functional_zone_origin: Callable[..., tuple[int, int]]
    functional_zones: tuple[str, ...]
    zone_max_cols: int
    auto_layout_origin_x_mm: float
    auto_layout_origin_y_mm: float
    auto_layout_column_spacing_mm: float
    auto_layout_row_spacing_mm: float
    warn: Callable[..., object]

    def auto_place_symbols(
        self,
        symbol_list: list[str] | None = None,
        strategy: str = "cluster",
    ) -> str:
        """Place references with the existing deterministic layout strategies."""
        payload = AutoPlaceSymbolsInput(
            symbol_list=symbol_list or [],
            strategy=cast(LayoutStrategy, strategy),
        )
        sch_file = self.active_schematic_file()
        try:
            schematic = self.load_schematic(sch_file)
        except Exception as exc:
            self.warn(
                "schematic_auto_place_load_failed",
                schematic_file=str(sch_file),
                error=str(exc),
            )
            return f"Could not load the active schematic for auto-placement: {exc}"

        sch_data = self.parse_schematic(sch_file)
        all_syms = sch_data["symbols"] + sch_data["power_symbols"]

        requested = payload.symbol_list or [str(sym["reference"]) for sym in sch_data["symbols"]]
        if not requested:
            return self.with_diagnostics(
                "The active schematic contains no symbols to auto-place.",
                sch_file,
            )

        requested_set = set(requested)
        fixed_syms = [s for s in all_syms if str(s.get("reference", "")) not in requested_set]
        occupied = self.estimate_occupied_cells(fixed_syms)

        placed = 0
        missing: list[str] = []
        radius_mm = self.auto_layout_column_spacing_mm * 2
        center_x = self.auto_layout_origin_x_mm + self.auto_layout_column_spacing_mm
        center_y = self.auto_layout_origin_y_mm + self.auto_layout_row_spacing_mm

        for index, reference in enumerate(requested):
            component = schematic.components.get(reference)
            if component is None:
                missing.append(reference)
                continue

            if payload.strategy == "linear":
                x, y = self.next_free_cell(
                    occupied,
                    start_col=index,
                    start_row=0,
                    max_cols=24,
                )
            elif payload.strategy == "star":
                if index == 0:
                    x = center_x
                    y = center_y
                    col = int(
                        round(
                            (x - self.auto_layout_origin_x_mm) / self.auto_layout_column_spacing_mm
                        )
                    )
                    row = int(
                        round((y - self.auto_layout_origin_y_mm) / self.auto_layout_row_spacing_mm)
                    )
                    occupied.add((col, row))
                else:
                    angle = ((index - 1) / max(len(requested) - 1, 1)) * (2 * math.pi)
                    raw_x = center_x + (radius_mm * math.cos(angle))
                    raw_y = center_y + (radius_mm * math.sin(angle))
                    col = int(
                        round(
                            (raw_x - self.auto_layout_origin_x_mm)
                            / self.auto_layout_column_spacing_mm
                        )
                    )
                    row = int(
                        round(
                            (raw_y - self.auto_layout_origin_y_mm) / self.auto_layout_row_spacing_mm
                        )
                    )
                    x, y = self.next_free_cell(occupied, start_col=col, start_row=row)
            elif payload.strategy == "grid":
                grid_cols = max(1, math.ceil(math.sqrt(len(requested))))
                x, y = self.next_free_cell(occupied, max_cols=grid_cols)
            else:
                x, y = self.next_free_cell(occupied)

            snapped_x, snapped_y = self.snap_point(x, y, True)
            component.move(snapped_x, snapped_y)
            placed += 1

        try:
            schematic.save(sch_file, preserve_format=True)
        except Exception as exc:
            self.warn(
                "schematic_auto_place_save_failed",
                schematic_file=str(sch_file),
                error=str(exc),
            )
            return f"Could not save auto-placement changes: {exc}"

        result = self.reload_schematic()
        missing_suffix = f" Missing: {', '.join(missing)}." if missing else ""
        return (
            f"{result}\n"
            f"Auto-placed {placed} symbol(s) using the {payload.strategy} strategy. "
            f"Overlap-aware placement respected {len(fixed_syms)} fixed obstacle(s)."
            f"{missing_suffix}"
        )

    def autoplace_fields(
        self,
        references: list[str] | None = None,
        dry_run: bool = False,
    ) -> str:
        """Reposition visible Reference/Value fields using existing helpers."""
        sch_file = self.active_schematic_file()
        mutator, targets, updated = self.build_autoplace_fields_mutator(sch_file, references)
        if not targets:
            return self.with_diagnostics(
                "No matching symbols found to auto-place fields for.", sch_file
            )

        if dry_run:
            mutator(sch_file.read_text(encoding="utf-8"))
            return (
                f"Dry run: would reposition Reference/Value fields on {len(updated)} "
                f"symbol(s): {', '.join(updated) if updated else '(none)'}."
            )

        self.transactional_write_to_schematic_file(sch_file, mutator)
        result = self.reload_schematic()
        return (
            f"{result}\n"
            f"Auto-placed Reference/Value fields on {len(updated)} symbol(s)"
            f"{': ' + ', '.join(updated) if updated else ''}."
        )

    def fix_readability(self, max_passes: int = 3) -> str:
        """Apply safe readability fixes until clean, stable, or pass-limited."""
        passes = max(1, max_passes)
        sch_file = self.active_schematic_file()
        actions: list[str] = []
        pass_log: list[str] = []
        initial_status: str | None = None
        final_status = "PASS"
        remaining: set[str] = set()

        for pass_index in range(passes):
            report = self.run_visual_qa(sch_file.read_text(encoding="utf-8", errors="ignore"))
            status = str(report["status"])
            findings = report["findings"]
            codes: set[str] = set()
            if isinstance(findings, list):
                for finding in cast(list[object], findings):
                    if not isinstance(finding, dict):
                        continue
                    code = cast(dict[str, object], finding).get("code")
                    if code is not None:
                        codes.add(str(code))
            if initial_status is None:
                initial_status = status
            final_status = status
            pass_log.append(
                f"pass {pass_index + 1}: {status} ({', '.join(sorted(codes)) or 'clean'})"
            )
            if status == "PASS":
                break

            changed = False
            if {"offsheet_symbol", "offsheet_label"} & codes:
                current_paper = self.read_sheet_paper(sch_file)
                ladder_index = (
                    self.paper_ladder.index(current_paper)
                    if current_paper in self.paper_ladder
                    else 0
                )
                if ladder_index < len(self.paper_ladder) - 1:
                    target = self.paper_ladder[ladder_index + 1]
                    if self.resize_sheet_apply(sch_file, target):
                        actions.append(f"grew sheet to {target}")
                        changed = True
            if "symbol_overlap" in codes and not self.schematic_has_connections(
                sch_file.read_text(encoding="utf-8", errors="ignore")
            ):
                respaced = self.respace_symbols_apply(sch_file)
                if respaced:
                    actions.append(f"re-spaced {len(respaced)} overlapping symbol(s)")
                    changed = True
            if "text_overlap" in codes:
                moved = self.autoplace_fields_apply(sch_file)
                if moved:
                    actions.append(f"auto-placed fields on {len(moved)} symbol(s)")
                    changed = True

            if not changed:
                remaining = codes
                break
            remaining = codes

        if actions:
            self.reload_schematic()

        unresolved = sorted(remaining & {"symbol_overlap", "label_overlap", "dense_label_fanout"})
        summary = [
            f"Readability fix: {initial_status or 'PASS'} -> {final_status} "
            f"over {len(pass_log)} pass(es).",
            *pass_log,
        ]
        if actions:
            summary.append("Applied: " + "; ".join(actions) + ".")
        else:
            summary.append("No automatic fixes were applied.")
        if unresolved:
            summary.append(
                "Manual follow-up suggested for: "
                + ", ".join(unresolved)
                + " (try sch_auto_place_functional / sch_auto_resize_sheet)."
            )
        return "\n".join(summary)

    def auto_place_functional(
        self,
        symbol_list: list[str] | None = None,
        anchor_ref: str | list[str] | None = None,
    ) -> str:
        """Place symbols into the existing semantic functional zones."""
        sch_file = self.active_schematic_file()
        try:
            schematic = self.load_schematic(sch_file)
        except Exception as exc:
            return f"Could not load the active schematic for functional placement: {exc}"

        sch_data = self.parse_schematic(sch_file)
        all_syms = sch_data["symbols"] + sch_data["power_symbols"]

        requested: list[str] = symbol_list or [str(s["reference"]) for s in sch_data["symbols"]]
        if not requested:
            return self.with_diagnostics(
                "The active schematic contains no symbols to place.",
                sch_file,
            )

        design_intent = self.load_design_intent()
        functional_spacing_mm = design_intent.functional_spacing_mm
        anchor_refs = self.normalize_anchor_refs(anchor_ref)
        anchor_set = set(anchor_refs)

        requested_set = set(requested)
        paper = self.read_sheet_paper(sch_file)
        max_cols = self.sheet_usable_cols(paper)
        max_rows = self.sheet_usable_rows(paper)
        default_size = self.paper_sizes_mm["A4"]
        sheet_w, sheet_h = self.paper_sizes_mm.get(paper, default_size)

        fixed_syms = [
            s
            for s in all_syms
            if str(s.get("reference", "")) not in requested_set
            or str(s.get("reference", "")) in anchor_set
        ]
        global_occupied = self.estimate_occupied_cells(fixed_syms)

        zone_occupied: dict[str, set[tuple[int, int]]] = {
            zone: set() for zone in self.functional_zones
        }

        sym_meta: dict[str, dict[str, str]] = {}
        for symbol in sch_data["symbols"]:
            ref = str(symbol.get("reference", ""))
            sym_meta[ref] = {
                "value": str(symbol.get("value", "")),
                "lib_id": str(symbol.get("lib_id", "")),
            }

        anchored_preserved = [
            ref for ref in anchor_refs if ref in requested_set and schematic.components.get(ref)
        ]
        for symbol in fixed_syms:
            reference = str(symbol.get("reference", ""))
            category = self.classify_symbol(
                ref=reference,
                value=sym_meta.get(reference, {}).get("value", ""),
                lib_id=sym_meta.get(reference, {}).get("lib_id", ""),
            )
            x = float(symbol.get("x", symbol.get("x_mm", 0.0)) or 0.0)
            y = float(symbol.get("y", symbol.get("y_mm", 0.0)) or 0.0)
            col = int(
                round((x - self.auto_layout_origin_x_mm) / self.auto_layout_column_spacing_mm)
            )
            row = int(round((y - self.auto_layout_origin_y_mm) / self.auto_layout_row_spacing_mm))
            zone_occupied.setdefault(category, set()).add((col, row))

        placed = 0
        overflow_count = 0
        missing: list[str] = []
        zone_counts: dict[str, int] = {}

        for reference in requested:
            if reference in anchor_set:
                continue
            component = schematic.components.get(reference)
            if component is None:
                missing.append(reference)
                continue

            meta = sym_meta.get(reference, {})
            category = self.classify_symbol(
                ref=reference,
                value=meta.get("value", ""),
                lib_id=meta.get("lib_id", ""),
            )

            zone_col, zone_row = self.functional_zone_origin(
                category,
                max_cols=max_cols,
                max_rows=max_rows,
                spacing_mm=functional_spacing_mm,
            )

            placed_in_zone = zone_occupied.setdefault(category, set())
            found = False
            col = zone_col
            row = zone_row
            for sub_row in range(0, max_rows):
                for sub_col in range(0, self.zone_max_cols):
                    cand_col = zone_col + sub_col
                    cand_row = zone_row + sub_row
                    if cand_col >= max_cols or cand_row >= max_rows:
                        continue
                    cell = (cand_col, cand_row)
                    if cell not in global_occupied and cell not in placed_in_zone:
                        col, row = cell
                        found = True
                        break
                if found:
                    break

            if not found:
                col_f, row_f = self.next_free_cell(global_occupied, paper=paper)
                col = int(
                    round(
                        (col_f - self.auto_layout_origin_x_mm) / self.auto_layout_column_spacing_mm
                    )
                )
                row = int(
                    round((row_f - self.auto_layout_origin_y_mm) / self.auto_layout_row_spacing_mm)
                )
                if col >= max_cols or row >= max_rows:
                    overflow_count += 1

            x = self.auto_layout_origin_x_mm + col * self.auto_layout_column_spacing_mm
            y = self.auto_layout_origin_y_mm + row * self.auto_layout_row_spacing_mm
            snapped_x, snapped_y = self.snap_point(x, y, True)

            component.move(snapped_x, snapped_y)
            placed += 1

            for dc in (-1, 0, 1):
                for dr in (-1, 0, 1):
                    global_occupied.add((col + dc, row + dr))
            placed_in_zone.add((col, row))
            zone_counts[category] = zone_counts.get(category, 0) + 1

        try:
            schematic.save(sch_file, preserve_format=True)
        except Exception as exc:
            return f"Could not save functional placement changes: {exc}"

        result = self.reload_schematic()
        missing_suffix = f" Missing refs: {', '.join(missing)}." if missing else ""
        anchor_suffix = (
            f"\nAnchored refs preserved: {', '.join(anchored_preserved)}."
            if anchored_preserved
            else ""
        )

        zone_lines = [f"  {cat}: {count}" for cat, count in sorted(zone_counts.items())]
        summary = "\n".join(zone_lines) if zone_lines else "  (none)"

        overflow_note = ""
        if overflow_count:
            overflow_note = (
                f"\nWARNING: {overflow_count} symbol(s) could not fit within the "
                f"'{paper}' sheet ({sheet_w:.0f}x{sheet_h:.0f} mm).  "
                "Call sch_auto_resize_sheet to switch to a larger format, "
                "then run sch_auto_place_functional again."
            )

        return (
            f"{result}\n"
            f"Functional auto-placement complete on '{paper}' sheet — "
            f"{placed} symbol(s) placed in {len(zone_counts)} zone(s):\n{summary}"
            f"\nFunctional spacing target: {functional_spacing_mm:.2f} mm."
            f"{anchor_suffix}{missing_suffix}{overflow_note}"
        )

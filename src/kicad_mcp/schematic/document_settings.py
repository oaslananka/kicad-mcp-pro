"""FastMCP-independent schematic document settings services."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from ..models.tool_result import MutatingToolResult, TransactionVerification


class TransactionalWrite(Protocol):
    def __call__(self, mutator: Callable[[str], str], path: Path, /) -> object: ...


class _SheetAlreadySetError(Exception):
    """Signal that the requested paper declaration is already present."""


@dataclass(frozen=True)
class SchematicDocumentSettingsService:
    """Edit schematic title metadata and sheet paper settings."""

    active_schematic_file: Callable[[], Path]
    resolve_target: Callable[..., Any]
    parse_schematic: Callable[[Path], dict[str, Any]]
    apply_title_block_updates: Callable[[str, dict[str, str]], str]
    transactional_write: TransactionalWrite
    reload_schematic: Callable[[], str]
    format_target_detail: Callable[[Any], str]
    read_sheet_paper: Callable[[Path], str]
    sheet_usable_cols: Callable[[str], int]
    sheet_usable_rows: Callable[[str], int]
    paper_sizes_mm: Mapping[str, tuple[float, float]]
    layout_origin_x_mm: float
    sheet_margin_mm: float
    symbol_half_width_mm: float
    symbol_half_height_mm: float

    def set_title_block_info(
        self,
        sheet: str | None = None,
        sheet_file: str | None = None,
        title: str | None = None,
        rev: str | None = None,
        date: str | None = None,
        company: str | None = None,
        comment1: str | None = None,
        comment2: str | None = None,
        comment3: str | None = None,
        comment4: str | None = None,
        dry_run: bool = False,
    ) -> str:
        updates = {
            key: value
            for key, value in {
                "title": title,
                "rev": rev,
                "date": date,
                "company": company,
                "comment1": comment1,
                "comment2": comment2,
                "comment3": comment3,
                "comment4": comment4,
            }.items()
            if value is not None
        }
        if not updates:
            return "No schematic title block fields specified. Provide at least one field."

        target = self.resolve_target(sheet=sheet, sheet_file=sheet_file)
        before_text = target.path.read_text(encoding="utf-8")
        planned_text = self.apply_title_block_updates(before_text, updates)
        changed = ", ".join(updates)
        changed_objects = [f"title_block.{field}" for field in updates]

        if dry_run:
            transaction = MutatingToolResult(
                changed_files=[str(target.path)],
                changed_objects=changed_objects,
                before_hash=hashlib.sha256(before_text.encode("utf-8")).hexdigest(),
                after_hash=hashlib.sha256(planned_text.encode("utf-8")).hexdigest(),
                verification=TransactionVerification(roundtrip="planned_not_written"),
                dry_run=True,
            )
            return transaction.to_compat_text(
                f"Dry run: schematic title block fields would be updated: {changed}."
            )

        self.transactional_write(
            lambda current: self.apply_title_block_updates(current, updates),
            target.path,
        )
        after_text = target.path.read_text(encoding="utf-8")
        result = self.reload_schematic()
        summary = (
            f"{result}\n{self.format_target_detail(target)}\n"
            f"Updated schematic title block fields: {changed}."
        )
        transaction = MutatingToolResult(
            changed_files=[str(target.path)],
            changed_objects=changed_objects,
            before_hash=hashlib.sha256(before_text.encode("utf-8")).hexdigest(),
            after_hash=hashlib.sha256(after_text.encode("utf-8")).hexdigest(),
            verification=TransactionVerification(roundtrip="validated"),
        )
        return transaction.to_compat_text(summary)

    def set_sheet_size(self, paper: str = "A3") -> str:
        paper = paper.strip()
        if paper not in self.paper_sizes_mm:
            available = ", ".join(sorted(self.paper_sizes_mm))
            return f"Unknown paper size '{paper}'. Available sizes: {available}."

        sch_file = self.active_schematic_file()
        new_w, new_h = self.paper_sizes_mm[paper]
        old_paper = "A4"

        def resize_sheet(current: str) -> str:
            nonlocal old_paper
            match = re.search(r'\(paper\s+"([^"]+)"(?:\s+[\d.]+\s+[\d.]+)?\)', current)
            old_paper = match.group(1) if match else "A4"

            if match is not None:
                new_text = re.sub(
                    r'\(paper\s+"[^"]+"(?:\s+[\d.]+\s+[\d.]+)?\)',
                    f'(paper "{paper}")',
                    current,
                    count=1,
                )
            else:
                new_text = re.sub(
                    r"(\(kicad_sch[^\n]*\n)",
                    rf'\1  (paper "{paper}")\n',
                    current,
                    count=1,
                )

            if new_text == current:
                raise _SheetAlreadySetError
            return new_text

        try:
            self.transactional_write(resize_sheet, sch_file)
        except _SheetAlreadySetError:
            return f"Sheet is already '{paper}' ({new_w:.0f} x {new_h:.0f} mm). No change made."
        except Exception as exc:
            return f"Could not write schematic file: {exc}"

        result = self.reload_schematic()
        old_w, old_h = self.paper_sizes_mm.get(old_paper, (0.0, 0.0))
        usable_cols = self.sheet_usable_cols(paper)
        usable_rows = self.sheet_usable_rows(paper)
        return (
            f"{result}\n"
            f"Sheet resized: {old_paper} ({old_w:.0f}x{old_h:.0f} mm) "
            f"-> {paper} ({new_w:.0f}x{new_h:.0f} mm).\n"
            f"Usable grid: {usable_cols} columns x {usable_rows} rows "
            f"(origin {self.layout_origin_x_mm} mm, margin {self.sheet_margin_mm} mm).\n"
            f"Tip: run sch_auto_place_functional to redistribute symbols on the new sheet."
        )

    def auto_resize_sheet(self) -> str:
        sch_file = self.active_schematic_file()
        sch_data = self.parse_schematic(sch_file)
        all_syms = sch_data["symbols"] + sch_data["power_symbols"]

        if not all_syms:
            return "No symbols found — sheet size unchanged."

        xs = [float(symbol.get("x", symbol.get("x_mm", 0.0)) or 0.0) for symbol in all_syms]
        ys = [float(symbol.get("y", symbol.get("y_mm", 0.0)) or 0.0) for symbol in all_syms]
        required_w = max(xs) + self.symbol_half_width_mm + self.sheet_margin_mm
        required_h = max(ys) + self.symbol_half_height_mm + self.sheet_margin_mm

        candidates = ["A4", "A3", "A2", "A1", "A0", "B", "C", "D", "E"]
        chosen = None
        for size in candidates:
            width, height = self.paper_sizes_mm[size]
            if width >= required_w and height >= required_h:
                chosen = size
                break

        current_paper = self.read_sheet_paper(sch_file)
        cur_w, cur_h = self.paper_sizes_mm.get(
            current_paper,
            self.paper_sizes_mm["A4"],
        )

        if chosen is None:
            return (
                f"Symbols span {required_w:.0f} x {required_h:.0f} mm — "
                "no standard size is large enough.  Consider splitting into "
                "hierarchical sheets (sch_create_sheet)."
            )

        if chosen == current_paper:
            return (
                f"Current sheet '{current_paper}' ({cur_w:.0f}x{cur_h:.0f} mm) "
                f"already fits all symbols (required {required_w:.0f}x{required_h:.0f} mm)."
            )

        return str(self.set_sheet_size(paper=chosen))

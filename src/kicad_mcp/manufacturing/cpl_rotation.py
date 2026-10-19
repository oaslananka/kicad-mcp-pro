"""FastMCP-independent JLCPCB CPL rotation correction service."""

from __future__ import annotations

import csv
import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PathResolver = Callable[[str], Path]

_DEFAULT_ROTATIONS_JSON = Path(__file__).parent.parent / "dfm_profiles" / "jlcpcb_rotations.json"


def load_rotation_table(path: Path = _DEFAULT_ROTATIONS_JSON) -> list[dict[str, Any]]:
    """Load JLCPCB rotation correction entries from the bundled JSON."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        entries = data.get("entries", [])
        if isinstance(entries, list):
            return [entry for entry in entries if isinstance(entry, dict)]
        return []
    except (OSError, json.JSONDecodeError):
        return []


def find_rotation_offset(
    footprint_name: str,
    table: list[dict[str, Any]],
) -> int | None:
    """Return the most-specific matching JLCPCB rotation offset."""
    name_upper = footprint_name.upper()
    best: tuple[int, int] | None = None
    for entry in table:
        pattern = entry.get("pattern", "").upper()
        if pattern and pattern in name_upper:
            length = len(pattern)
            if best is None or length > best[0]:
                best = (length, int(entry.get("offset_deg", 0)))
    return best[1] if best else None


def _read_cpl_rows(in_path: Path) -> tuple[list[str], list[dict[str, str]]] | str:
    try:
        with in_path.open(newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            if reader.fieldnames is None:
                return "CPL CSV has no header row."
            return list(reader.fieldnames), list(reader)
    except (OSError, csv.Error) as exc:
        return f"Failed to read CPL CSV: {exc}"


def _resolve_cpl_columns(fieldnames: list[str]) -> tuple[str, str] | str:
    rot_col = "Rot"
    pkg_col = "Package"
    for col in fieldnames:
        if col.lower() in ("rot", "rotation"):
            rot_col = col
        if col.lower() in ("package", "footprint"):
            pkg_col = col

    if rot_col not in fieldnames:
        return f"Rotation column ('{rot_col}') not found in CSV. Columns: {fieldnames}"
    if pkg_col not in fieldnames:
        return f"Package column ('{pkg_col}') not found in CSV. Columns: {fieldnames}"
    return rot_col, pkg_col


def _apply_rotation_corrections(
    rows: list[dict[str, str]],
    table: list[dict[str, Any]],
    rot_col: str,
    pkg_col: str,
) -> tuple[int, list[str]]:
    corrected_count = 0
    preview_lines = [
        "Ref | Package | Original Rot | Offset | Corrected Rot",
        "----|---------|-------------|--------|---------------",
    ]

    for row in rows:
        pkg = row.get(pkg_col, "")
        offset = find_rotation_offset(pkg, table)
        if offset is not None and offset != 0:
            try:
                orig = float(row[rot_col])
            except ValueError:
                continue
            corrected = (orig + offset) % 360
            row[rot_col] = f"{corrected:.2f}"
            corrected_count += 1
            ref = row.get("Ref", "?")
            preview_lines.append(f"{ref} | {pkg} | {orig:.2f}° | +{offset}° | {corrected:.2f}°")

    return corrected_count, preview_lines


def _write_cpl_csv(
    out_path: Path,
    fieldnames: list[str],
    rows: list[dict[str, str]],
) -> str | None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with out_path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
    except OSError as exc:
        return f"Failed to write corrected CPL CSV: {exc}"
    return None


@dataclass(frozen=True)
class ManufacturingCplRotationService:
    """Correct JLCPCB CPL rotations without depending on MCP transport types."""

    resolve_path: PathResolver
    rotation_table_path: Path = _DEFAULT_ROTATIONS_JSON

    def correct(
        self,
        cpl_csv_path: str,
        *,
        output_path: str = "",
        dry_run: bool = True,
        confirm: bool = False,
    ) -> str:
        in_path = self.resolve_path(cpl_csv_path)
        if not in_path.exists():
            return f"CPL file not found: {in_path}"

        table = load_rotation_table(self.rotation_table_path)
        if not table:
            return "Could not load rotation table from jlcpcb_rotations.json."

        csv_result = _read_cpl_rows(in_path)
        if isinstance(csv_result, str):
            return csv_result
        fieldnames, rows = csv_result

        cols_result = _resolve_cpl_columns(fieldnames)
        if isinstance(cols_result, str):
            return cols_result
        rot_col, pkg_col = cols_result

        corrected_count, preview_lines = _apply_rotation_corrections(rows, table, rot_col, pkg_col)

        if output_path:
            out_path = self.resolve_path(output_path)
        else:
            out_path = in_path.parent / f"{in_path.stem}_jlcpcb_corrected.csv"

        if dry_run:
            if corrected_count == 0:
                return "No rotation corrections needed for any component."
            return (
                f"Dry run: {corrected_count} component(s) would be corrected.\n"
                f"Output would be: {out_path}\n\n"
                + "\n".join(preview_lines[:50])
                + ("\n...(truncated)" if len(preview_lines) > 50 else "")
            )
        if not confirm:
            return (
                "CPL rotation correction writes a new CSV and requires explicit confirmation.\n"
                f"- Intended output: {out_path}\n"
                "Rerun with dry_run=false and confirm=true."
            )
        if out_path.exists():
            return (
                "Refusing to overwrite an existing corrected CPL CSV.\n"
                f"- Existing file: {out_path}\n"
                "Choose a different output_path."
            )

        write_err = _write_cpl_csv(out_path, fieldnames, rows)
        if write_err:
            return write_err

        return (
            f"CPL rotation corrections applied: {corrected_count} component(s) corrected.\n"
            f"Output: {out_path}\n\n"
            + "\n".join(preview_lines[:30])
            + ("\n…" if len(preview_lines) > 30 else "")
        )

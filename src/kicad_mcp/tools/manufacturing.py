"""Manufacturing tools: panelization (KiKit), test-plan generation, and release manifest.

Tools in this module complement ``export_manufacturing_package`` with:
- ``mfg_panelize`` — wrap KiKit CLI for grid/mousebites/V-cut panels.
- ``mfg_generate_test_plan`` — generate a bring-up test checklist from design intent.
- ``mfg_generate_release_manifest`` — produce a SHA256-signed release manifest JSON.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any, Literal

import structlog
from mcp.server.mcpserver import MCPServer as FastMCP

from ..config import get_config
from .metadata import headless_compatible

logger = structlog.get_logger(__name__)

PanelLayout = Literal["grid", "mousebites", "vcut"]

# Path to the rotation correction table
_ROTATIONS_JSON = Path(__file__).parent.parent / "dfm_profiles" / "jlcpcb_rotations.json"


def _load_rotation_table() -> list[dict[str, Any]]:
    """Load JLCPCB rotation correction entries from the bundled JSON."""
    try:
        data = json.loads(_ROTATIONS_JSON.read_text(encoding="utf-8"))
        entries = data.get("entries", [])
        if isinstance(entries, list):
            return [entry for entry in entries if isinstance(entry, dict)]
        return []
    except (OSError, json.JSONDecodeError):
        return []


def _find_rotation_offset(
    footprint_name: str,
    table: list[dict[str, Any]],
) -> int | None:
    """Return the rotation offset (degrees) for a footprint, or None if not found.

    Matching is case-insensitive substring: the pattern must appear in the
    footprint name.  More specific patterns (longer) take precedence.
    """
    name_upper = footprint_name.upper()
    best: tuple[int, int] | None = None  # (length, offset)
    for entry in table:
        pattern = entry.get("pattern", "").upper()
        if pattern and pattern in name_upper:
            length = len(pattern)
            if best is None or length > best[0]:
                best = (length, int(entry.get("offset_deg", 0)))
    return best[1] if best else None


def _kikit_available() -> bool:
    return shutil.which("kikit") is not None


def register(mcp: FastMCP) -> None:
    """Register manufacturing tools."""

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
        if not _kikit_available():
            return (
                "KiKit is not installed. "
                "Install it with: pip install kikit\n"
                "KiKit documentation: https://github.com/yaqwsx/KiKit"
            )

        cfg = get_config()
        if cfg.pcb_file is None or not cfg.pcb_file.exists():
            return "No PCB file is configured. Call kicad_set_project() first."

        layout_lower = layout.lower()
        if layout_lower not in ("grid", "mousebites", "vcut"):
            return f"Invalid layout '{layout}'. Choose from: grid, mousebites, vcut."

        if rows < 1 or cols < 1:
            return "rows and cols must both be >= 1."

        out_dir = cfg.ensure_output_dir("panel")

        board_stem = cfg.pcb_file.stem
        if output_path:
            panel_file = cfg.resolve_within_project(output_path)
        else:
            panel_file = out_dir / f"{board_stem}_panel_{rows}x{cols}.kicad_pcb"

        # Build KiKit command
        if layout_lower == "grid":
            cmd = [
                "kikit",
                "panelize",
                "--layout",
                f"grid; rows: {rows}; cols: {cols}; space: {spacing_mm}mm",
                "--tabs",
                "fixed; width: 3mm; count: 1",
                "--cuts",
                "mousebites; drill: 0.5mm; spacing: 0.8mm",
                "--framing",
                f"railstb; width: {frame_width_mm}mm",
                "--post",
                "millRoundedCorner",
                str(cfg.pcb_file),
                str(panel_file),
            ]
        elif layout_lower == "mousebites":
            cmd = [
                "kikit",
                "panelize",
                "--layout",
                f"grid; rows: {rows}; cols: {cols}; space: {spacing_mm}mm",
                "--tabs",
                "fixed; width: 3mm; count: 2",
                "--cuts",
                "mousebites; drill: 0.5mm; spacing: 0.8mm; offset: 0.25mm",
                "--framing",
                f"railstb; width: {frame_width_mm}mm",
                str(cfg.pcb_file),
                str(panel_file),
            ]
        else:  # vcut
            cmd = [
                "kikit",
                "panelize",
                "--layout",
                f"grid; rows: {rows}; cols: {cols}; space: 0mm",
                "--tabs",
                "full",
                "--cuts",
                "vcuts; clearance: 0.5mm",
                "--framing",
                f"railstb; width: {frame_width_mm}mm",
                str(cfg.pcb_file),
                str(panel_file),
            ]

        if dry_run:
            return (
                "Dry run: panelization was not executed.\n"
                f"- Output: {panel_file}\n"
                f"- Layout: {layout_lower} {rows}x{cols}, spacing={spacing_mm}mm, "
                f"frame={frame_width_mm}mm\n"
                f"- Command: {' '.join(cmd)}\n"
                "Set dry_run=false and confirm=true to create the panel file."
            )
        if not confirm:
            return (
                "Panelization requires explicit confirmation because it writes a PCB file.\n"
                f"- Intended output: {panel_file}\n"
                "Rerun with dry_run=false and confirm=true."
            )
        if panel_file.exists():
            return (
                "Refusing to overwrite an existing panel file without choosing a new output_path.\n"
                f"- Existing file: {panel_file}"
            )

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                errors="replace",
                timeout=120,
            )
        except subprocess.TimeoutExpired:
            return "KiKit panelization timed out after 120 seconds."
        except (OSError, FileNotFoundError) as exc:
            return f"Failed to run KiKit: {exc}"

        if result.returncode != 0:
            stderr = (result.stderr or "").strip()[:500]
            return f"KiKit panelization failed (exit {result.returncode}):\n{stderr}"

        return (
            f"Panel created: {panel_file}\n"
            f"Layout: {layout} {rows}x{cols}, spacing={spacing_mm}mm, frame={frame_width_mm}mm\n"
            f"Open the panel file in KiCad to verify before submitting to fabricator."
        )

    from . import manufacturing_test_plan

    manufacturing_test_plan.register(mcp)

    from . import manufacturing_release_manifest

    manufacturing_release_manifest.register(mcp)

    @mcp.tool()
    @headless_compatible
    def mfg_correct_cpl_rotations(
        cpl_csv_path: str,
        output_path: str = "",
        dry_run: bool = True,
        confirm: bool = False,
    ) -> str:
        """Apply JLCPCB CPL rotation corrections to a KiCad-exported pick-and-place CSV.

        KiCad exports component orientations relative to its own coordinate system,
        which differs from what JLCPCB's SMT assembly service expects.  This tool
        reads a CPL CSV (produced by export_pos), applies per-footprint rotation
        offsets from the bundled ``jlcpcb_rotations.json`` table, and writes a
        corrected CSV ready for direct upload to JLCPCB.

        Columns expected (KiCad default CPL export):
            Ref, Val, Package, PosX, PosY, Rot, Side

        Args:
            cpl_csv_path: Path to the CPL CSV file (relative to project dir).
            output_path: Output path for the corrected CSV.  Defaults to
                ``<stem>_jlcpcb_corrected.csv`` next to the input file.
            dry_run: If True, return a preview table without writing the file.
            confirm: Must be True when ``dry_run`` is False and a file will be written.

        Returns:
            Summary of corrections applied, or a preview table for dry_run.
        """
        import csv

        cfg = get_config()
        in_path = cfg.resolve_within_project(cpl_csv_path)

        if not in_path.exists():
            return f"CPL file not found: {in_path}"

        table = _load_rotation_table()
        if not table:
            return "Could not load rotation table from jlcpcb_rotations.json."

        # Parse CSV
        rows: list[dict[str, str]] = []
        try:
            with in_path.open(newline="", encoding="utf-8") as fh:
                reader = csv.DictReader(fh)
                if reader.fieldnames is None:
                    return "CPL CSV has no header row."
                fieldnames = list(reader.fieldnames)
                rows = list(reader)
        except (OSError, csv.Error) as exc:
            return f"Failed to read CPL CSV: {exc}"

        # Detect rotation column name (KiCad uses 'Rot' or 'Rotation')
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

        corrected_count = 0
        preview_lines: list[str] = ["Ref | Package | Original Rot | Offset | Corrected Rot"]
        preview_lines.append("----|---------|-------------|--------|---------------")

        for row in rows:
            pkg = row.get(pkg_col, "")
            offset = _find_rotation_offset(pkg, table)
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

        if output_path:
            out_path = cfg.resolve_within_project(output_path)
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

        # Write corrected CSV
        out_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with out_path.open("w", newline="", encoding="utf-8") as fh:
                writer = csv.DictWriter(fh, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)
        except OSError as exc:
            return f"Failed to write corrected CPL CSV: {exc}"

        return (
            f"CPL rotation corrections applied: {corrected_count} component(s) corrected.\n"
            f"Output: {out_path}\n\n"
            + "\n".join(preview_lines[:30])
            + ("\n…" if len(preview_lines) > 30 else "")
        )

    from . import manufacturing_imports

    manufacturing_imports.register(mcp)

    from . import manufacturing_release_evidence

    manufacturing_release_evidence.register(mcp)

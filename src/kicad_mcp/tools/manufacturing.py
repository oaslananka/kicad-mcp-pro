"""Manufacturing tools: panelization (KiKit), test-plan generation, and release manifest.

Tools in this module complement ``export_manufacturing_package`` with:
- ``mfg_panelize`` — wrap KiKit CLI for grid/mousebites/V-cut panels.
- ``mfg_generate_test_plan`` — generate a bring-up test checklist from design intent.
- ``mfg_generate_release_manifest`` — produce a SHA256-signed release manifest JSON.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import structlog
from mcp.server.mcpserver import MCPServer as FastMCP

from .. import __version__
from ..config import get_config
from ..discovery import get_cli_capabilities
from ..manufacturing.release_evidence import find_release_files, sha256_file
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


def register(mcp: FastMCP) -> None:
    """Register manufacturing tools."""

    from . import manufacturing_panelization

    manufacturing_panelization.register(mcp)

    from . import manufacturing_test_plan

    manufacturing_test_plan.register(mcp)

    @mcp.tool()
    @headless_compatible
    def mfg_generate_release_manifest(output_path: str = "") -> str:
        """Generate a SHA256-signed release manifest for the manufacturing package.

        Collects all files in the output directory, computes SHA256 hashes, and
        records tool versions, intent hash, and gate status into a ``manifest.json``
        and ``MANIFEST.txt``.

        Args:
            output_path: Subdirectory inside the project (defaults to ``output/``).

        Returns:
            Confirmation with manifest path and file count.
        """
        from .project import load_design_intent

        cfg = get_config()
        out_dir = cfg.output_dir or (cfg.project_dir / "output")  # type: ignore[operator]

        if not out_dir.exists():
            return (
                f"Output directory does not exist: {out_dir}\n"
                "Run export_manufacturing_package() first."
            )

        # Gather all files
        release_files = find_release_files(out_dir)
        if not release_files:
            return (
                "No release files found in output directory.\n"
                "Run export_manufacturing_package() first to generate Gerber/drill/BOM files."
            )

        # Compute per-file hashes, sorted by name for deterministic, reproducible output.
        file_hashes: list[dict[str, str]] = sorted(
            (
                {
                    "filename": f.name,
                    "sha256": sha256_file(f),
                    "size_bytes": str(f.stat().st_size),
                }
                for f in release_files
            ),
            key=lambda entry: entry["filename"],
        )

        # Intent hash
        intent = load_design_intent()
        intent_json = json.dumps(intent.model_dump(), sort_keys=True)
        intent_hash = hashlib.sha256(intent_json.encode()).hexdigest()[:16]

        # Provenance: what produced this package (kept out of the wall-clock path so the
        # content_hash stays stable across runs for identical inputs).
        caps = get_cli_capabilities(cfg.kicad_cli)
        source_hashes = {
            label: sha256_file(path)
            for label, path in (
                ("project", cfg.project_file),
                ("pcb", cfg.pcb_file),
                ("schematic", cfg.sch_file),
            )
            if path is not None and path.exists()
        }
        provenance: dict[str, Any] = {
            "kicad_mcp_version": __version__,
            "kicad_cli": str(cfg.kicad_cli),
            "kicad_cli_version": caps.version,
            "intent_hash": intent_hash,
            "source_hashes": source_hashes,
        }

        # content_hash is a stable fingerprint of the package contents plus what produced
        # them: identical inputs -> identical content_hash, regardless of generation time.
        content_basis = json.dumps({"files": file_hashes, "provenance": provenance}, sort_keys=True)
        content_hash = hashlib.sha256(content_basis.encode()).hexdigest()

        manifest: dict[str, Any] = {
            "kicad_mcp_version": __version__,
            "generated_utc": datetime.now(UTC).isoformat(),
            "content_hash": content_hash,
            "intent_hash": intent_hash,
            "provenance": provenance,
            "files": file_hashes,
        }

        # Write manifest.json
        manifest_json_path = out_dir / "manifest.json"
        manifest_json_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

        # Write MANIFEST.txt (human-readable)
        txt_lines = [
            "kicad-mcp-pro Release Manifest",
            f"Generated: {manifest['generated_utc']}",
            f"Tool version: kicad-mcp-pro {__version__}",
            f"KiCad CLI version: {caps.version or 'unknown'}",
            f"Content hash: {content_hash}",
            f"Intent hash: {intent_hash}",
            "",
            f"{'Filename':<50} {'SHA256':>16}",
            "-" * 70,
        ]
        for entry in file_hashes:
            txt_lines.append(f"{entry['filename']:<50} {entry['sha256'][:16]}")

        manifest_txt_path = out_dir / "MANIFEST.txt"
        manifest_txt_path.write_text("\n".join(txt_lines), encoding="utf-8")

        return (
            f"Release manifest generated:\n"
            f"- {manifest_json_path} ({len(file_hashes)} files)\n"
            f"- {manifest_txt_path}\n"
            f"Content hash: {content_hash}\n"
            f"Intent hash: {intent_hash}\n"
            f"Files covered: {', '.join(e['filename'] for e in file_hashes[:10])}"
            + ("…" if len(file_hashes) > 10 else "")
        )

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

"""Manufacturing tools: panelization (KiKit), test-plan generation, and release manifest.

Tools in this module complement ``export_manufacturing_package`` with:
- ``mfg_panelize`` — wrap KiKit CLI for grid/mousebites/V-cut panels.
- ``mfg_generate_test_plan`` — generate a bring-up test checklist from design intent.
- ``mfg_generate_release_manifest`` — produce a SHA256-signed release manifest JSON.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
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

    @mcp.tool()
    @headless_compatible
    def mfg_generate_test_plan(output_path: str = "", confirm_overwrite: bool = False) -> str:
        """Generate a bring-up test plan from the project design intent.

        Produces a structured markdown checklist covering:
        - Power-on sequence and current limit checks for each power rail.
        - Protocol loopback / link-up checks for each interface.
        - Critical-net continuity probes.
        - Visual inspection items.

        Args:
            output_path: Optional relative path for saving the plan (e.g.
                ``"test_plan.md"``). If omitted, returns the plan as text only.
            confirm_overwrite: If True, allow overwriting an existing output file.

        Returns:
            Bring-up test plan in markdown format.
        """
        from .project import load_design_intent

        intent = load_design_intent()

        lines: list[str] = [
            "# Bring-Up Test Plan",
            f"Generated: {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}",
            "",
        ]

        # Power-on sequence
        lines += [
            "## 1. Power-On Sequence",
            "",
            "**Prerequisites:** Board assembled, no loads connected, current-limited PSU.",
            "",
        ]
        if intent.power_rails:
            lines.append("| Step | Rail | Target (V) | Max (A) | Tolerance | Action |")
            lines.append("|------|------|-----------|---------|-----------|--------|")
            for i, rail in enumerate(intent.power_rails, start=1):
                v_min = rail.voltage_v * (1 - rail.tolerance_pct / 100)
                v_max = rail.voltage_v * (1 + rail.tolerance_pct / 100)
                lines.append(
                    f"| {i} | {rail.name} | {rail.voltage_v:.2f}V | "
                    f"{rail.current_max_a:.1f}A | "
                    f"[{v_min:.3f}, {v_max:.3f}]V | "
                    f"Measure at {rail.source_ref or 'source'}, check no smoke |"
                )
        else:
            lines += [
                "- [ ] Apply primary supply — measure and verify voltage within spec.",
                "- [ ] Confirm current draw is within expected range.",
                "- [ ] Verify all power rails reach target voltage.",
            ]

        # Continuity
        lines += [
            "",
            "## 2. Critical-Net Continuity",
            "",
        ]
        if intent.critical_nets:
            for net in intent.critical_nets[:20]:
                lines.append(f"- [ ] Probe `{net}` — verify continuity from source to load.")
        else:
            lines.append("- [ ] (No critical nets defined in design intent.)")

        # Interface checks
        lines += [
            "",
            "## 3. Interface Link-Up Tests",
            "",
        ]
        if intent.interfaces:
            for iface in intent.interfaces:
                kind = iface.kind
                refs_str = ", ".join(iface.refs[:5]) if iface.refs else "(see schematic)"
                lines.append(f"### {kind.upper()} ({refs_str})")
                interface_checks: dict[str, list[str]] = {
                    "usb2": [
                        "Connect USB analyzer or host device.",
                        "Verify USB enumeration (lsusb or device manager).",
                        "Run USB compliance test tool if available.",
                    ],
                    "usb3": [
                        "Connect USB 3.x SuperSpeed host.",
                        "Verify SuperSpeed enumeration and link training.",
                        "Measure eye diagram at connector.",
                    ],
                    "ethernet_1000": [
                        "Connect Ethernet cable to link partner.",
                        "Verify 1000BASE-T auto-negotiation (link LED).",
                        "Run iperf3 bidirectional throughput test.",
                    ],
                    "pcie_g3": [
                        "Install into PCIe x1/x4/x16 slot.",
                        "Verify PCIe link training (lspci -vvv).",
                        "Check link width and speed negotiation.",
                    ],
                    "can": [
                        "Connect to CAN bus with 120ohm termination.",
                        "Send/receive test frames with CAN analyzer.",
                        "Verify no error frames at operational baud rate.",
                    ],
                    "i2c": [
                        "Scan I2C bus — verify device ACKs (i2cdetect -y 1).",
                        "Read/write device registers to confirm communication.",
                    ],
                    "uart": [
                        "Connect UART terminal (115200 8N1).",
                        "Verify TX loopback and receive data.",
                    ],
                    "swd": [
                        "Connect debug probe (J-Link / ST-Link / DAPLink).",
                        "Verify MCU detected and halts cleanly.",
                        "Flash test firmware and verify execution.",
                    ],
                }
                checks = interface_checks.get(
                    kind,
                    [f"Verify {kind} communication with appropriate test equipment."],
                )
                for check in checks:
                    lines.append(f"  - [ ] {check}")
                lines.append("")
        else:
            lines.append("- [ ] (No interfaces defined in design intent.)")

        # Visual inspection
        lines += [
            "",
            "## 4. Visual Inspection",
            "",
            "- [ ] Verify all connectors seated correctly.",
            "- [ ] Inspect for solder bridges on fine-pitch components.",
            "- [ ] Verify correct component orientation (polarised capacitors, diodes, ICs).",
            "- [ ] Check mechanical mounting and keep-out clearances.",
        ]

        if intent.compliance:
            lines += [
                "",
                "## 5. Compliance Pre-Checks",
                "",
            ]
            for ct in intent.compliance:
                lines.append(f"- [ ] Prepare for **{ct.kind.upper()}** certification.")
                if ct.notes:
                    lines.append(f"  Note: {ct.notes}")

        text = "\n".join(lines)

        cfg = get_config()
        if output_path:
            out_file = cfg.resolve_within_project(output_path)
            if out_file.exists() and not confirm_overwrite:
                return (
                    "Refusing to overwrite an existing test plan without confirmation.\n"
                    f"- Existing file: {out_file}\n"
                    "Rerun with confirm_overwrite=true or choose a different output_path."
                )
            out_file.parent.mkdir(parents=True, exist_ok=True)
            out_file.write_text(text, encoding="utf-8")
            return f"Test plan saved to {out_file}\n\n" + text

        return text

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

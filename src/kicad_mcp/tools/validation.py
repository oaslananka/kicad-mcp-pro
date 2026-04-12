"""Validation and design-check tools."""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

from mcp.server.fastmcp import FastMCP

from ..config import get_config
from .export import _ensure_output_dir, _get_pcb_file, _get_sch_file, _run_cli_variants


def _load_report(path: Path) -> dict[str, object]:
    return cast(dict[str, object], json.loads(path.read_text(encoding="utf-8")))


def _entries(report: dict[str, object], key: str) -> list[dict[str, object]]:
    return cast(list[dict[str, object]], report.get(key, []))


def _format_violations(title: str, entries: list[dict[str, object]]) -> str:
    if not entries:
        return f"{title}: none"
    lines = [f"{title} ({len(entries)} total):"]
    for entry in entries[: get_config().max_items_per_response]:
        severity = str(entry.get("severity", "?"))
        description = str(entry.get("description", "(no description)"))
        lines.append(f"- [{severity}] {description}")
    return "\n".join(lines)


def _run_drc_report(report_name: str) -> tuple[Path, dict[str, object] | None, str | None]:
    pcb_file = _get_pcb_file()
    out_file = _ensure_output_dir() / report_name
    code, _, stderr = _run_cli_variants(
        [
            [
                "pcb",
                "drc",
                "--output",
                str(out_file),
                "--format",
                "json",
                "--severity-all",
                "--exit-code-violations",
                str(pcb_file),
            ],
            [
                "pcb",
                "drc",
                "--input",
                str(pcb_file),
                "--output",
                str(out_file),
                "--format",
                "json",
                "--severity-all",
                "--exit-code-violations",
            ],
        ]
    )
    if not out_file.exists():
        return out_file, None, stderr if code != 0 else "DRC report was not produced."
    return out_file, _load_report(out_file), None


def _run_erc_report(report_name: str) -> tuple[Path, dict[str, object] | None, str | None]:
    sch_file = _get_sch_file()
    out_file = _ensure_output_dir() / report_name
    code, _, stderr = _run_cli_variants(
        [
            [
                "sch",
                "erc",
                "--output",
                str(out_file),
                "--format",
                "json",
                "--severity-all",
                "--exit-code-violations",
                str(sch_file),
            ],
            [
                "sch",
                "erc",
                "--input",
                str(sch_file),
                "--output",
                str(out_file),
                "--format",
                "json",
                "--severity-all",
                "--exit-code-violations",
            ],
        ]
    )
    if not out_file.exists():
        return out_file, None, stderr if code != 0 else "ERC report was not produced."
    return out_file, _load_report(out_file), None


def register(mcp: FastMCP) -> None:
    """Register validation tools."""

    @mcp.tool()
    def run_drc(save_report: bool = False) -> str:
        """Run PCB design rule checks."""
        path, report, error = _run_drc_report("drc_report.json")
        if report is None:
            return f"DRC failed: {error or 'unknown error'}"

        violations = _entries(report, "violations")
        unconnected = _entries(report, "unconnected_items")
        courtyard = _entries(report, "items_not_passing_courtyard")
        lines = [
            "DRC summary:",
            f"- Violations: {len(violations)}",
            f"- Unconnected items: {len(unconnected)}",
            f"- Courtyard issues: {len(courtyard)}",
        ]
        if violations:
            lines.append(_format_violations("Violations", violations))
        if save_report:
            lines.append(f"Saved report: {path}")
        return "\n".join(lines)

    @mcp.tool()
    def run_erc(save_report: bool = False) -> str:
        """Run schematic electrical rule checks."""
        path, report, error = _run_erc_report("erc_report.json")
        if report is None:
            return f"ERC failed: {error or 'unknown error'}"

        violations = _entries(report, "violations")
        lines = ["ERC summary:", f"- Violations: {len(violations)}"]
        if violations:
            lines.append(_format_violations("Violations", violations))
        if save_report:
            lines.append(f"Saved report: {path}")
        return "\n".join(lines)

    @mcp.tool()
    def validate_design() -> str:
        """Run DRC and ERC and summarize readiness."""
        _, drc_report, drc_error = _run_drc_report("validate_drc.json")
        _, erc_report, erc_error = _run_erc_report("validate_erc.json")

        lines = ["Design validation summary:"]
        if drc_report is not None:
            lines.append(
                f"- DRC: {len(_entries(drc_report, 'violations'))} violations, "
                f"{len(_entries(drc_report, 'unconnected_items'))} unconnected items"
            )
        else:
            lines.append(f"- DRC: unavailable ({drc_error})")

        if erc_report is not None:
            lines.append(f"- ERC: {len(_entries(erc_report, 'violations'))} violations")
        else:
            lines.append(f"- ERC: unavailable ({erc_error})")
        return "\n".join(lines)

    @mcp.tool()
    def check_design_for_manufacture(jlcpcb: bool = True) -> str:
        """Run a lightweight DFM check using available DRC data."""
        _, report, error = _run_drc_report("dfm_drc.json")
        if report is None:
            return f"DFM check failed: {error or 'unknown error'}"

        violations = _entries(report, "violations")
        unconnected = _entries(report, "unconnected_items")
        courtyard = _entries(report, "items_not_passing_courtyard")
        silk = [
            violation
            for violation in violations
            if "silk" in str(violation.get("description", "")).lower()
        ]
        lines = [
            f"DFM check ({'JLCPCB' if jlcpcb else 'generic'} profile):",
            f"- Total DRC violations: {len(violations)}",
            f"- Unconnected items: {len(unconnected)}",
            f"- Courtyard issues: {len(courtyard)}",
            f"- Silk to copper hints: {len(silk)}",
        ]
        if jlcpcb:
            lines.append(
                "Review annular ring, solder mask expansion, and slot support before fabrication."
            )
        return "\n".join(lines)

    @mcp.tool()
    def get_unconnected_nets() -> str:
        """Return only unconnected net issues from DRC."""
        _, report, error = _run_drc_report("unconnected.json")
        if report is None:
            return f"Unable to compute unconnected nets: {error or 'unknown error'}"

        entries = _entries(report, "unconnected_items")
        if not entries:
            return "No unconnected nets were reported."
        return _format_violations("Unconnected nets", entries)

    @mcp.tool()
    def get_courtyard_violations() -> str:
        """Return only courtyard issues from DRC."""
        _, report, error = _run_drc_report("courtyard.json")
        if report is None:
            return f"Unable to compute courtyard issues: {error or 'unknown error'}"

        entries = _entries(report, "items_not_passing_courtyard")
        if not entries:
            return "No courtyard violations were reported."
        return _format_violations("Courtyard violations", entries)

    @mcp.tool()
    def get_silk_to_pad_violations() -> str:
        """Return silkscreen overlap issues from DRC."""
        _, report, error = _run_drc_report("silk_to_pad.json")
        if report is None:
            return f"Unable to compute silk-to-pad issues: {error or 'unknown error'}"

        entries = [
            entry
            for entry in _entries(report, "violations")
            if "silk" in str(entry.get("description", "")).lower()
            and "pad" in str(entry.get("description", "")).lower()
        ]
        if not entries:
            return "No silk-to-pad violations were reported."
        return _format_violations("Silk-to-pad violations", entries)

    @mcp.tool()
    def validate_footprints_vs_schematic() -> str:
        """Compare PCB footprint references against the schematic symbol references."""
        from ..connection import get_board
        from .schematic import parse_schematic_file

        cfg = get_config()
        if cfg.sch_file is None or cfg.pcb_file is None:
            return "Both a schematic and PCB file must be configured for comparison."

        schematic = parse_schematic_file(cfg.sch_file)
        schematic_refs = {symbol["reference"] for symbol in schematic["symbols"]}
        board_refs = {
            footprint.reference_field.text.value for footprint in get_board().get_footprints()
        }

        missing_on_board = sorted(schematic_refs - board_refs)
        missing_in_schematic = sorted(board_refs - schematic_refs)
        lines = [
            "Footprint versus schematic comparison:",
            f"- References in schematic: {len(schematic_refs)}",
            f"- Footprints on board: {len(board_refs)}",
            f"- Missing on board: {len(missing_on_board)}",
            f"- Missing in schematic: {len(missing_in_schematic)}",
        ]
        if missing_on_board:
            lines.append("Missing on board: " + ", ".join(missing_on_board[:20]))
        if missing_in_schematic:
            lines.append("Missing in schematic: " + ", ".join(missing_in_schematic[:20]))
        return "\n".join(lines)

"""Visual / readability QA tools (issue #153).

Thin MCP wrapper over the headless visual-QA engine in ``models/visual_qa.py``.
The engine works purely from schematic S-expression geometry, so these tools run
fully headless without KiCad or a render backend.
"""

from __future__ import annotations

import json

from mcp.server.fastmcp import FastMCP

from ..models import visual_qa
from .metadata import headless_compatible

_STATUS_ORDER = {"PASS": 0, "INFO": 0, "WARN": 1, "FAIL": 2}


def register(mcp: FastMCP) -> None:
    """Register schematic visual-QA tools."""

    @mcp.tool()
    @headless_compatible
    def sch_visual_qa() -> str:
        """Run headless visual/readability QA on the active schematic sheet(s).

        Detects readability defects ERC cannot — overlapping labels, off-sheet
        symbols or labels, dense unreadable label fanout, and title-block gaps —
        directly from the schematic S-expression geometry, with no rendering
        required. Returns JSON with an overall PASS/WARN/FAIL status and per-sheet
        findings carrying object refs and positions for follow-up.
        """
        from .schematic import project_schematic_files

        sheets: list[dict[str, object]] = []
        for sch_file in project_schematic_files():
            try:
                text = sch_file.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            report = visual_qa.run_visual_qa(text)
            report["file"] = sch_file.name
            sheets.append(report)

        if not sheets:
            return json.dumps({"error": "No schematic files found for the active project."})

        overall = "PASS"
        for sheet in sheets:
            status = str(sheet.get("status", "PASS"))
            if _STATUS_ORDER.get(status, 0) > _STATUS_ORDER.get(overall, 0):
                overall = status
        return json.dumps({"status": overall, "sheets": sheets}, indent=2)

    @mcp.tool()
    @headless_compatible
    def sch_cosmetic_score() -> str:
        """Score the active schematic's cosmetic quality on a 0-100 scale.

        Extends readability QA with the traits that separate a professional sheet
        from a merely-working one: on-grid placement, orthogonal wiring, consistent
        typography, upright power/ground symbols, and balanced sheet composition.
        Returns a deterministic per-sheet and overall score with a per-category
        penalty breakdown and the worst category to fix first — the loop signal for
        the visual-excellence workflow. No rendering or live KiCad required.
        """
        from .schematic import project_schematic_files

        sheets: list[dict[str, object]] = []
        for sch_file in project_schematic_files():
            try:
                text = sch_file.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            report = visual_qa.run_cosmetic_qa(text)
            report["file"] = sch_file.name
            sheets.append(report)

        if not sheets:
            return json.dumps({"error": "No schematic files found for the active project."})

        # Overall score is the worst (lowest) sheet — a design is only as polished
        # as its least-polished page.
        def _sheet_score(sheet: dict[str, object]) -> float:
            value = sheet.get("cosmetic_score", 0.0)
            return float(value) if isinstance(value, (int, float)) else 0.0

        overall_score = min(_sheet_score(sheet) for sheet in sheets)
        overall_status = "PASS"
        for sheet in sheets:
            status = str(sheet.get("status", "PASS"))
            if _STATUS_ORDER.get(status, 0) > _STATUS_ORDER.get(overall_status, 0):
                overall_status = status
        return json.dumps(
            {
                "cosmetic_score": round(overall_score, 1),
                "status": overall_status,
                "sheets": sheets,
            },
            indent=2,
        )

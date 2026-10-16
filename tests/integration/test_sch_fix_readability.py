"""Integration tests for the sch_fix_readability closed loop (generate -> QA -> fix)."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from kicad_mcp.server import build_server
from tests.conftest import call_tool_text


async def _add_two_resistors(server: object) -> None:
    for ref, x in (("R1", 100.0), ("R2", 120.0)):
        await call_tool_text(
            server,
            "sch_add_symbol",
            {
                "library": "Device",
                "symbol_name": "R",
                "x_mm": x,
                "y_mm": 100.0,
                "reference": ref,
                "value": "10k",
            },
        )


def _collide_reference_fields(sch_file: Path) -> None:
    text = sch_file.read_text(encoding="utf-8")
    text = re.sub(
        r'(\(property\s+"Reference"\s+"R\d+"\s*\(at\s+)[-\d.]+\s+[-\d.]+\s+[-\d.]+(\))',
        r"\g<1>110 100 0\g<2>",
        text,
    )
    sch_file.write_text(text, encoding="utf-8")


def _qa_codes(raw: str) -> set[str]:
    payload = json.loads(raw)
    return {
        finding["code"]
        for sheet in payload.get("sheets", [])
        for finding in sheet.get("findings", [])
    }


@pytest.mark.anyio
async def test_fix_readability_clears_text_overlap(sample_project, mock_kicad) -> None:
    server = build_server("schematic")
    await _add_two_resistors(server)
    sch_file = sample_project / "demo.kicad_sch"
    _collide_reference_fields(sch_file)

    assert "text_overlap" in _qa_codes(await call_tool_text(server, "sch_visual_qa", {}))

    result = await call_tool_text(server, "sch_fix_readability", {})
    assert "Readability fix" in result
    assert "auto-placed fields" in result

    assert "text_overlap" not in _qa_codes(await call_tool_text(server, "sch_visual_qa", {}))


@pytest.mark.anyio
async def test_fix_readability_grows_sheet_for_offsheet(sample_project, mock_kicad) -> None:
    server = build_server("schematic")
    # Place a symbol well outside the A4 sheet boundary.
    await call_tool_text(
        server,
        "sch_add_symbol",
        {
            "library": "Device",
            "symbol_name": "R",
            "x_mm": 100.0,
            "y_mm": 100.0,
            "reference": "R1",
            "value": "10k",
            "snap_to_grid": False,
        },
    )
    sch_file = sample_project / "demo.kicad_sch"
    # Drag the symbol off the right edge of A4 (297 mm wide).
    text = sch_file.read_text(encoding="utf-8")
    text = text.replace("(at 100 100 0)", "(at 400 100 0)", 1)
    sch_file.write_text(text, encoding="utf-8")

    assert "offsheet_symbol" in _qa_codes(await call_tool_text(server, "sch_visual_qa", {}))

    result = await call_tool_text(server, "sch_fix_readability", {"max_passes": 4})
    assert "grew sheet" in result

    paper = re.search(r'\(paper\s+"([^"]+)"', sch_file.read_text(encoding="utf-8"))
    assert paper is not None
    assert paper.group(1) != "A4"


@pytest.mark.anyio
async def test_fix_readability_respaces_unconnected_overlap(sample_project, mock_kicad) -> None:
    server = build_server("schematic")
    # Two resistors stacked on the same coordinate, with no wires/labels: a bag of
    # unconnected symbols that is safe to re-space.
    for ref in ("R1", "R2"):
        await call_tool_text(
            server,
            "sch_add_symbol",
            {
                "library": "Device",
                "symbol_name": "R",
                "x_mm": 100.0,
                "y_mm": 100.0,
                "reference": ref,
                "value": "10k",
            },
        )
    # Force exact overlap: move both symbols onto the same point.
    for ref in ("R1", "R2"):
        await call_tool_text(
            server,
            "sch_move_symbol",
            {"reference": ref, "x_mm": 100.0, "y_mm": 100.0, "snap_to_grid": False},
        )

    assert "symbol_overlap" in _qa_codes(await call_tool_text(server, "sch_visual_qa", {}))

    result = await call_tool_text(server, "sch_fix_readability", {})
    assert "re-spaced" in result
    assert "symbol_overlap" not in _qa_codes(await call_tool_text(server, "sch_visual_qa", {}))


@pytest.mark.anyio
async def test_fix_readability_keeps_connected_symbols_in_place(sample_project, mock_kicad) -> None:
    server = build_server("schematic")
    for ref in ("R1", "R2"):
        await call_tool_text(
            server,
            "sch_add_symbol",
            {
                "library": "Device",
                "symbol_name": "R",
                "x_mm": 100.0,
                "y_mm": 100.0,
                "reference": ref,
                "value": "10k",
            },
        )
    for ref in ("R1", "R2"):
        await call_tool_text(
            server,
            "sch_move_symbol",
            {"reference": ref, "x_mm": 100.0, "y_mm": 100.0, "snap_to_grid": False},
        )
    # Add a wire so the sheet is "connected" — re-spacing must NOT run.
    await call_tool_text(
        server,
        "sch_add_wire",
        {"x1_mm": 100.0, "y1_mm": 100.0, "x2_mm": 110.0, "y2_mm": 100.0},
    )

    result = await call_tool_text(server, "sch_fix_readability", {})
    assert "re-spaced" not in result


@pytest.mark.anyio
async def test_fix_readability_reports_clean_when_nothing_to_do(sample_project, mock_kicad) -> None:
    server = build_server("schematic")
    await call_tool_text(
        server,
        "sch_add_symbol",
        {
            "library": "Device",
            "symbol_name": "R",
            "x_mm": 100.0,
            "y_mm": 100.0,
            "reference": "R1",
            "value": "10k",
        },
    )
    result = await call_tool_text(server, "sch_fix_readability", {})
    # A single clean resistor needs no fixes; the title block is the only finding.
    assert "No automatic fixes were applied." in result

"""Integration test: build_circuit grows the sheet so nothing lands off-page."""

from __future__ import annotations

import json
import re

import pytest

from kicad_mcp.server import build_server
from tests.conftest import call_tool_text


@pytest.mark.anyio
async def test_build_circuit_auto_layout_grows_paper(sample_project, mock_kicad) -> None:
    server = build_server("schematic")
    symbols = [
        {"library": "Device", "symbol_name": "R", "reference": f"R{i}", "value": "10k"}
        for i in range(80)
    ]

    await call_tool_text(
        server,
        "sch_build_circuit",
        {"symbols": symbols, "auto_layout": True},
    )

    sch_text = (sample_project / "demo.kicad_sch").read_text(encoding="utf-8")
    paper = re.search(r'\(paper\s+"([^"]+)"', sch_text)
    assert paper is not None
    # 80 parts do not fit an A4 grid, so the sheet must have grown.
    assert paper.group(1) != "A4"

    raw = await call_tool_text(server, "sch_visual_qa", {})
    payload = json.loads(raw)
    codes = {
        finding["code"]
        for sheet in payload.get("sheets", [])
        for finding in sheet.get("findings", [])
    }
    assert "offsheet_symbol" not in codes


@pytest.mark.anyio
async def test_build_circuit_default_max_paper_caps_at_a3(sample_project, mock_kicad) -> None:
    server = build_server("schematic")
    # Enough parts that the old unbounded climb reached A2; the A3 default cap
    # must keep the sheet at A3 and pack multiple columns/rows instead.
    symbols = [
        {"library": "Device", "symbol_name": "R", "reference": f"R{i}", "value": "10k"}
        for i in range(200)
    ]

    await call_tool_text(
        server,
        "sch_build_circuit",
        {"symbols": symbols, "auto_layout": True},
    )

    sch_text = (sample_project / "demo.kicad_sch").read_text(encoding="utf-8")
    paper = re.search(r'\(paper\s+"([^"]+)"', sch_text)
    assert paper is not None
    assert paper.group(1) == "A3"

    # Multiple rows and columns are used (not a single oversized row).
    at_positions = re.findall(r"\(symbol\b.*?\(at\s+([\d.]+)\s+([\d.]+)", sch_text, re.DOTALL)
    xs = {round(float(x), 1) for x, _y in at_positions}
    ys = {round(float(y), 1) for _x, y in at_positions}
    assert len(xs) > 1
    assert len(ys) > 1


@pytest.mark.anyio
async def test_build_circuit_max_paper_a2_permits_a2(sample_project, mock_kicad) -> None:
    server = build_server("schematic")
    symbols = [
        {"library": "Device", "symbol_name": "R", "reference": f"R{i}", "value": "10k"}
        for i in range(400)
    ]

    await call_tool_text(
        server,
        "sch_build_circuit",
        {"symbols": symbols, "auto_layout": True, "max_paper": "A2"},
    )

    sch_text = (sample_project / "demo.kicad_sch").read_text(encoding="utf-8")
    paper = re.search(r'\(paper\s+"([^"]+)"', sch_text)
    assert paper is not None
    assert paper.group(1) == "A2"


@pytest.mark.anyio
async def test_build_circuit_invalid_max_paper_raises(sample_project, mock_kicad) -> None:
    server = build_server("schematic")
    symbols = [{"library": "Device", "symbol_name": "R", "reference": "R1", "value": "10k"}]

    # FastMCP wraps the ValueError as a tool error; the message is surfaced in
    # the returned content.
    text = await call_tool_text(
        server,
        "sch_build_circuit",
        {"symbols": symbols, "auto_layout": True, "max_paper": "A9"},
    )
    assert "Invalid max_paper" in text

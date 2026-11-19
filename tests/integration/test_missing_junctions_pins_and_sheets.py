"""Regression: sch_add_missing_junctions must follow KiCad's junction rule.

KiCad draws (and needs) a junction dot where three or more connection ends
meet: wire ends and pin ends. The repair only found a wire end landing on
another wire's middle (a T), so a pin with two wires ending on it, or three
wires ending at one point, were left without a dot. It also only worked on the
active schematic.

Two cases must never get an automatic dot, because a dot there would change
connectivity rather than just show it: wires that merely cross, and a pin that
sits on the middle of a wire (KiCad 10 leaves that pin unconnected). The second
one is reported instead.
"""

from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from mcp.server.mcpserver import MCPServer

from kicad_mcp.server import build_server
from kicad_mcp.tools.schematic import wire_block
from tests.conftest import call_tool_text

ROOT_UUID = "00000000-0000-0000-0000-000000000000"
SHEET_UUID = "11111111-1111-4111-8111-111111111111"

# Device:R in the test library is horizontal: pin 1 at x - 2.54, pin 2 at x + 2.54.
WIRES = [
    # A: two wires end on R1 pin 1 (99.06, 101.6): pin + 2 wire ends -> dot.
    (99.06, 101.6, 99.06, 91.44),
    (99.06, 101.6, 88.9, 101.6),
    # B: three wires end at one point (127, 76.2) -> dot.
    (127.0, 76.2, 127.0, 66.04),
    (127.0, 76.2, 116.84, 76.2),
    (127.0, 76.2, 137.16, 76.2),
    # C: a T, wire end on another wire's middle (60.96, 50.8) -> dot (as before).
    (50.8, 50.8, 71.12, 50.8),
    (60.96, 50.8, 60.96, 40.64),
    # D: a wire passes through R2 pin 1 (99.06, 127): no dot, reported.
    (99.06, 121.92, 99.06, 132.08),
    # E: two wires cross at (60.96, 76.2): never a dot.
    (50.8, 76.2, 71.12, 76.2),
    (60.96, 66.04, 60.96, 86.36),
    # F: two wires meet end to end at (40.64, 30.48): no dot needed.
    (30.48, 30.48, 40.64, 30.48),
    (40.64, 30.48, 50.8, 30.48),
]
EXPECTED_DOTS = {(99.06, 101.6), (127.0, 76.2), (60.96, 50.8)}

_JUNCTION = re.compile(r"\(junction\s*\(at\s+([-\d.]+)\s+([-\d.]+)\)")


def _junctions(sheet: Path) -> set[tuple[float, float]]:
    text = sheet.read_text(encoding="utf-8")
    return {(float(x), float(y)) for x, y in _JUNCTION.findall(text)}


def _append_wires(sheet: Path) -> None:
    text = sheet.read_text(encoding="utf-8")
    blocks = "\n".join(wire_block(*wire) for wire in WIRES) + "\n"
    anchor = "\t(sheet_instances" if "\t(sheet_instances" in text else "\t(embedded_fonts"
    sheet.write_text(text.replace(anchor, blocks + anchor, 1), encoding="utf-8")


async def _place_resistors(server: MCPServer, sheet_file: str | None) -> None:
    for reference, y_mm in (("R1", 101.6), ("R2", 127.0)):
        arguments: dict[str, object] = {
            "library": "Device",
            "symbol_name": "R",
            "x_mm": 101.6,
            "y_mm": y_mm,
            "reference": reference,
            "value": "10k",
        }
        if sheet_file is not None:
            arguments["sheet_file"] = sheet_file
        await call_tool_text(server, "sch_add_symbol", arguments)


def _assert_repaired(result: str, sheet: Path) -> None:
    assert _junctions(sheet) == EXPECTED_DOTS, (result, _junctions(sheet))
    assert "Inserted 3 missing junction(s)." in result, result
    assert "R2 pin 1 at (99.06, 127" in result, result


@pytest.mark.anyio
async def test_junctions_follow_kicad_rule_on_the_active_sheet(
    sample_project: Path, mock_kicad: MagicMock
) -> None:
    server = build_server("schematic")
    sheet = sample_project / "demo.kicad_sch"
    await _place_resistors(server, None)
    _append_wires(sheet)

    result = await call_tool_text(server, "sch_add_missing_junctions", {})

    _assert_repaired(result, sheet)


@pytest.mark.anyio
async def test_junctions_can_be_repaired_on_a_child_sheet(
    sample_project: Path, mock_kicad: MagicMock
) -> None:
    root = sample_project / "demo.kicad_sch"
    child = sample_project / "child.kicad_sch"
    child.write_text(
        root.read_text(encoding="utf-8").replace(ROOT_UUID, SHEET_UUID), encoding="utf-8"
    )
    server = build_server("schematic")
    await _place_resistors(server, "child.kicad_sch")
    _append_wires(child)
    root_before = root.read_text(encoding="utf-8")

    result = await call_tool_text(
        server, "sch_add_missing_junctions", {"sheet_file": "child.kicad_sch"}
    )

    _assert_repaired(result, child)
    assert root.read_text(encoding="utf-8") == root_before

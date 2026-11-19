"""Regression: pcb_sync_from_schematic must notice pad nets that changed in the schematic.

The sync only added missing footprints and replaced ones with the wrong
footprint name. When the schematic moved a net to another pin of a part that is
already on the board (a pin swap), it said "The PCB already contains all
schematic footprint assignments." and left the old pad nets in place.
"""

from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from mcp.server.mcpserver import MCPServer

from kicad_mcp.server import build_server
from kicad_mcp.validation.gates import GateOutcome
from tests.conftest import call_tool_text

ORIGINAL_NETS = {
    ("R1", "1"): "VIN",
    ("R1", "2"): "MID",
    ("R2", "1"): "MID",
    ("R2", "2"): "GND",
}
# R1's two pins swapped in the schematic; R2 unchanged.
SWAPPED_NETS = {**ORIGINAL_NETS, ("R1", "1"): "MID", ("R1", "2"): "VIN"}


def _allow_sync(monkeypatch: pytest.MonkeyPatch, nets: dict[tuple[str, str], str]) -> None:
    for gate in ("_evaluate_schematic_gate", "_evaluate_schematic_connectivity_gate"):
        monkeypatch.setattr(
            f"kicad_mcp.tools.validation.{gate}",
            lambda: GateOutcome(name="Schematic", status="PASS", summary="ok", details=[]),
            raising=False,
        )
    monkeypatch.setattr("kicad_mcp.tools.pcb._board_is_open", lambda: False)
    monkeypatch.setattr("kicad_mcp.tools.pcb._export_schematic_net_map", lambda: (dict(nets), ""))


def _footprint(pcb_text: str, reference: str) -> str:
    for block in re.split(r"\n\t\(footprint ", pcb_text)[1:]:
        if f'(property "Reference" "{reference}"' in block:
            return block
    raise AssertionError(f"{reference} not on the board")


def _pad_nets(block: str) -> dict[str, str]:
    nets: dict[str, str] = {}
    for pad in re.split(r"\(pad ", block)[1:]:
        number = re.match(r'"([^"]*)"', pad)
        net = re.search(r'\(net "([^"]*)"\)', pad.split("\n\t\t)", 1)[0])
        if number:
            nets[number.group(1)] = net.group(1) if net else ""
    return nets


async def _board_with_two_resistors(
    server: MCPServer, project: Path, monkeypatch: pytest.MonkeyPatch
) -> Path:
    _allow_sync(monkeypatch, ORIGINAL_NETS)
    await call_tool_text(
        server,
        "sch_build_circuit",
        {
            "symbols": [
                {
                    "library": "Device",
                    "symbol_name": "R",
                    "reference": reference,
                    "value": "10k",
                    "footprint": "Resistor_SMD:R_0805",
                    "x_mm": x_mm,
                    "y_mm": 50.8,
                }
                for reference, x_mm in (("R1", 50.8), ("R2", 76.2))
            ]
        },
    )
    result = await call_tool_text(server, "pcb_sync_from_schematic", {"auto_place": False})
    assert "New footprints added: 2" in result, result
    return project / "demo.kicad_pcb"


@pytest.mark.anyio
async def test_sync_reports_and_updates_pad_nets_after_a_pin_swap(
    sample_project: Path, mock_kicad: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    server = build_server("full")
    board = await _board_with_two_resistors(server, sample_project, monkeypatch)
    before = board.read_text(encoding="utf-8")
    r1_before = _footprint(before, "R1")
    r2_before = _footprint(before, "R2")
    assert _pad_nets(r1_before) == {"1": "VIN", "2": "MID"}

    _allow_sync(monkeypatch, SWAPPED_NETS)

    # Default: report the stale pads, change nothing.
    report = await call_tool_text(server, "pcb_sync_from_schematic", {"auto_place": False})
    assert "Pad nets out of date on existing footprints: 2" in report, report
    assert "- R1.1: VIN -> MID" in report
    assert "- R1.2: MID -> VIN" in report
    assert "update_pad_nets=True" in report
    assert board.read_text(encoding="utf-8") == before

    # Opt in: only R1's pad nets change.
    updated = await call_tool_text(
        server, "pcb_sync_from_schematic", {"update_pad_nets": True, "auto_place": True}
    )
    assert "Pad nets updated on existing footprints: 2" in updated, updated
    after = board.read_text(encoding="utf-8")
    r1_after = _footprint(after, "R1")
    assert _pad_nets(r1_after) == {"1": "MID", "2": "VIN"}
    assert _footprint(after, "R2") == r2_before
    # Nothing but the two (net ...) nodes moved: same position, fields and pads.
    assert re.sub(r'\(net "[^"]*"\)', "", r1_after) == re.sub(r'\(net "[^"]*"\)', "", r1_before)

    again = await call_tool_text(server, "pcb_sync_from_schematic", {"update_pad_nets": True})
    assert "Pad nets" not in again, again
    assert board.read_text(encoding="utf-8") == after

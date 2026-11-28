"""Opt-in native placement coordinate frame and footprint-lock acceptance."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from kicad_mcp.config import get_config, reset_config
from kicad_mcp.connection import reset_connection
from kicad_mcp.pcb.live_edit_runtime import reset_live_edit_service
from kicad_mcp.tools import pcb, validation
from tests.gui.test_native_ipc_discovery_recovery import (
    FIXTURE,
    _configure_private_project,
    _installed_bin_dir,
)
from tests.integration.test_native_mounting_hole_keepout import _append_objects, _drc_types
from tests.integration.test_routing_native_drc_preflight import _run_native_python

OPT_IN = "KICAD_NATIVE_WINDOWS_PLACEMENT_BIN"
pytestmark = [
    pytest.mark.slow,
    pytest.mark.skipif(
        sys.platform != "win32" or not os.environ.get(OPT_IN),
        reason=f"Set {OPT_IN} to an installed KiCad 10.0 bin directory on Windows",
    ),
]

_NATIVE_PREPARE = """
import pcbnew
import sys

board = pcbnew.LoadBoard(sys.argv[1])
for footprint in board.GetFootprints():
    if footprint.GetReference() == "R1":
        footprint.SetLocked(sys.argv[2] == "locked")
assert pcbnew.SaveBoard(sys.argv[1], board)
"""


def _assert_native_drc_parity(board: Path, report: Path) -> None:
    assert _drc_types(board, report) == []
    data = json.loads(report.read_text(encoding="utf-8"))
    assert len(data["unconnected_items"]) == 1


@pytest.mark.parametrize("locked", [False, True])
def test_native_translated_board_placement_preserves_drc(
    monkeypatch: pytest.MonkeyPatch, locked: bool
) -> None:
    bin_dir = _installed_bin_dir(os.environ[OPT_IN])
    root = bin_dir.parent / "share/kicad/footprints"
    stock = root / "Resistor_SMD.pretty/R_0603_1608Metric.kicad_mod"
    source_bytes = FIXTURE.read_bytes()
    stock_bytes = stock.read_bytes()
    with TemporaryDirectory(prefix="kicad-placement-") as scratch, monkeypatch.context() as mp:
        board, env, _ = _configure_private_project(Path(scratch), bin_dir, mp)
        try:
            for key in ("KICAD10_TEMPLATE_DIR", "KICAD10_SYMBOL_DIR", "KICAD10_FOOTPRINT_DIR"):
                mp.setenv(key, env[key])
            get_config().footprint_library_dir = root
            get_config().pcb_file = board
            baseline = (
                board.read_text(encoding="utf-8")
                .replace("(version 20240101)", "(version 20250316)")
                .replace("(start 0 0) (end 100 60)", "(start 60 40) (end 100 70)")
            )
            blocks = [
                pcb._render_board_footprint_block(
                    "Resistor_SMD:R_0603_1608Metric",
                    reference=ref,
                    value="10k",
                    x_mm=x,
                    y_mm=y,
                    rotation=0,
                    pad_nets={"1": "SIGNAL"},
                )
                for ref, x, y in (("R1", 70, 50), ("R2", 90, 60))
            ]
            _append_objects(board, baseline, *blocks)
            _run_native_python(
                bin_dir / "python.exe",
                _NATIVE_PREPARE,
                board,
                Path("locked" if locked else "unlocked"),
                env=env,
            )
            before = board.read_text(encoding="utf-8")
            original = pcb._parse_board_footprint_blocks(before)
            assert set(original) == {"R1", "R2"}
            assert all(e["pad_nets"].get("1") == "SIGNAL" for e in original.values())
            _assert_native_drc_parity(board, board.with_name("before.json"))
            initial = validation._placement_analysis_from_content(before)
            assert initial is not None
            assert initial.score == 100
            assert not initial.hard_failures

            message = pcb._auto_place_force_directed_board_file()
            assert "completed" in message, message
            after = board.read_text(encoding="utf-8")
            assert after != before
            entries = pcb._parse_board_footprint_blocks(after)
            assert {r: e["pad_nets"] for r, e in entries.items()} == {
                r: e["pad_nets"] for r, e in original.items()
            }
            r1 = (entries["R1"]["x_mm"], entries["R1"]["y_mm"])
            r2 = (entries["R2"]["x_mm"], entries["R2"]["y_mm"])
            if locked:
                assert r1 == (70, 50)
                assert entries["R1"]["block"] == original["R1"]["block"]
                assert r2 != (90, 60)
            else:
                assert r1 == (77, 54)
                assert r2 == (83, 56)
            final = validation._placement_analysis_from_content(after)
            assert final is not None
            assert final.score == 100
            assert not final.hard_failures
            _assert_native_drc_parity(board, board.with_name("after.json"))
        finally:
            reset_config()
            reset_connection()
            reset_live_edit_service()
    assert FIXTURE.read_bytes() == source_bytes
    assert stock.read_bytes() == stock_bytes

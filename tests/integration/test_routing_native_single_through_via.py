"""Opt-in native KiCad 10 front-to-back via routing preflight on a scratch PCB."""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from kicad_mcp.config import get_config
from kicad_mcp.pcb.route_drc_preflight import run_route_drc_preflight
from kicad_mcp.routing.manual_tracks import TrackSpec, ViaSpec

pytestmark = pytest.mark.skipif(
    os.environ.get("KICAD_MCP_RUN_ROUTING_NATIVE_PREFLIGHT") != "1",
    reason="Only run with native KiCad PCB Python/CLI on a disposable PCB",
)

_CHANGE_ENDPAD_TO_B_CU = """
import pcbnew
import sys
from pathlib import Path

file = Path(sys.argv[1])
board = pcbnew.LoadBoard(str(file))
assert board is not None
assert len(list(board.GetTracks())) == 0
matched = False
for footprint in board.GetFootprints():
    if footprint.GetReference() == "R2":
        for pad in footprint.Pads():
            if pad.GetNumber() == "1":
                assert pad.GetNetname() == "MID"
                layer_set = pcbnew.LSET()
                for layer in (pcbnew.B_Cu, pcbnew.B_Mask, pcbnew.B_Paste):
                    layer_set.AddLayer(layer)
                pad.SetLayerSet(layer_set)
                matched = True
assert matched
pcbnew.SaveBoard(str(file), board)
readback = pcbnew.LoadBoard(str(file))
assert readback is not None
target = next(
    p for f in readback.GetFootprints() if f.GetReference() == "R2"
    for p in f.Pads() if p.GetNumber() == "1"
)
assert target.IsOnLayer(pcbnew.B_Cu)
assert not target.IsOnLayer(pcbnew.F_Cu)
"""


def test_native_through_via_connects_front_smd_to_back_smd(tmp_path: Path) -> None:
    cli = get_config().kicad_cli
    native_python = cli.parent / ("python.exe" if cli.suffix.lower() == ".exe" else "python3")
    if not cli.is_file() or not native_python.is_file():
        pytest.skip("KiCad native board Python and CLI unavailable")
    source = (
        Path(__file__).resolve().parents[1]
        / "fixtures"
        / "benchmark_projects"
        / "fail_dirty_transfer_wrong_pad_nets"
    )
    original = source / "demo.kicad_pcb"
    original_hash = hashlib.sha256(original.read_bytes()).hexdigest()
    project = tmp_path / "demo.kicad_pro"
    board = tmp_path / "demo.kicad_pcb"
    shutil.copy2(source / "demo.kicad_pro", project)
    shutil.copy2(original, board)
    proc = subprocess.run(
        [str(native_python), "-c", _CHANGE_ENDPAD_TO_B_CU, str(board)],
        capture_output=True,
        text=True,
        timeout=40,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr[-1200:]
    baseline_hash = hashlib.sha256(board.read_bytes()).hexdigest()
    project_hash = hashlib.sha256(project.read_bytes()).hexdigest()
    via = ViaSpec(15, 10, 0.8, 0.4, "MID")
    tracks = [
        TrackSpec(10.95, 10, 15, 10, "F_Cu", 0.25, "MID"),
        TrackSpec(15, 10, 19.05, 10, "B_Cu", 0.25, "MID"),
    ]
    evidence = run_route_drc_preflight(
        board.read_text(encoding="utf-8"),
        tracks,
        project_file=project,
        kicad_cli=cli,
        through_via=via,
    )
    assert evidence == {
        "accepted": True,
        "introducedViolations": 0,
        "unconnectedBefore": 1,
        "unconnectedAfter": 0,
    }
    assert hashlib.sha256(board.read_bytes()).hexdigest() == baseline_hash
    assert hashlib.sha256(project.read_bytes()).hexdigest() == project_hash
    assert hashlib.sha256(original.read_bytes()).hexdigest() == original_hash

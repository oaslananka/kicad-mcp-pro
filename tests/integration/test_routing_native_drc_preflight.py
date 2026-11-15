"""Opt-in real KiCad CLI/SWIG routing DRC acceptance on a disposable fixture."""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from kicad_mcp.config import get_config
from kicad_mcp.pcb.route_drc_preflight import run_route_drc_preflight
from kicad_mcp.routing.manual_tracks import TrackSpec

pytestmark = pytest.mark.skipif(
    os.environ.get("KICAD_MCP_RUN_ROUTING_NATIVE_PREFLIGHT") != "1",
    reason="Only run on an authorized KiCad host with native PCB Python and CLI",
)


def test_native_preflight_accepts_connected_route_but_rejects_new_shorts() -> None:
    root = (
        Path(__file__).resolve().parents[1]
        / "fixtures"
        / "benchmark_projects"
        / "fail_dirty_transfer_wrong_pad_nets"
    )
    pcb = root / "demo.kicad_pcb"
    project = root / "demo.kicad_pro"
    source = pcb.read_bytes()
    digest = hashlib.sha256(source).hexdigest()
    config = get_config()
    cli = config.kicad_cli
    if not cli.is_file() or not (cli.parent / "python.exe").is_file():
        pytest.skip("KiCad-bundled native Python/CLI not installed")

    good = run_route_drc_preflight(
        source.decode("utf-8"),
        [TrackSpec(10.95, 10, 19.05, 10, "F_Cu", 0.25, "MID")],
        project_file=project,
        kicad_cli=cli,
    )
    bad = run_route_drc_preflight(
        source.decode("utf-8"),
        [TrackSpec(9.05, 10, 19.05, 10, "F_Cu", 0.25, "MID")],
        project_file=project,
        kicad_cli=cli,
    )

    assert good == {
        "accepted": True,
        "introducedViolations": 0,
        "unconnectedBefore": 1,
        "unconnectedAfter": 0,
    }
    assert bad["accepted"] is False
    assert bad["introducedViolations"] >= 1
    assert hashlib.sha256(pcb.read_bytes()).hexdigest() == digest


def test_native_preflight_connects_two_through_hole_pads_on_back_copper(
    tmp_path: Path,
) -> None:
    """Use a disposable native KiCad PTH board, preserving source fixture bytes."""
    root = (
        Path(__file__).resolve().parents[1]
        / "fixtures"
        / "benchmark_projects"
        / "fail_dirty_transfer_wrong_pad_nets"
    )
    source = root / "demo.kicad_pcb"
    baseline_sha = hashlib.sha256(source.read_bytes()).hexdigest()
    project = tmp_path / "demo.kicad_pro"
    pcb = tmp_path / "demo.kicad_pcb"
    shutil.copy2(root / "demo.kicad_pro", project)
    shutil.copy2(source, pcb)

    cli = get_config().kicad_cli
    native_python = cli.parent / "python.exe"
    if not cli.is_file() or not native_python.is_file():
        pytest.skip("KiCad-bundled native Python and CLI unavailable")
    native_conversion = """
import pcbnew
import sys

board = pcbnew.LoadBoard(sys.argv[1])
assert board is not None
identities = {("R1", "2"), ("R2", "1")}
converted = set()
for footprint in board.GetFootprints():
    for pad in footprint.Pads():
        key = (footprint.GetReference(), pad.GetNumber())
        if key not in identities:
            continue
        assert pad.GetNetname() == "MID"
        pad.SetAttribute(pcbnew.PAD_ATTRIB_PTH)
        pad.SetDrillSize(
            pcbnew.VECTOR2I(pcbnew.FromMM(0.35), pcbnew.FromMM(0.35))
        )
        layers = pcbnew.LSET.AllCuMask()
        layers.AddLayer(pcbnew.F_Mask)
        layers.AddLayer(pcbnew.B_Mask)
        pad.SetLayerSet(layers)
        converted.add(key)
assert converted == identities
pcbnew.SaveBoard(sys.argv[1], board)
"""
    result = subprocess.run(
        [str(native_python), "-c", native_conversion, str(pcb)],
        capture_output=True,
        text=True,
        timeout=40,
        check=False,
    )
    assert result.returncode == 0, result.stderr[-1000:]

    evidence = run_route_drc_preflight(
        pcb.read_text(encoding="utf-8"),
        [TrackSpec(10.95, 10, 19.05, 10, "B_Cu", 0.25, "MID")],
        project_file=project,
        kicad_cli=cli,
    )
    assert evidence == {
        "accepted": True,
        "introducedViolations": 0,
        "unconnectedBefore": 1,
        "unconnectedAfter": 0,
    }
    assert hashlib.sha256(source.read_bytes()).hexdigest() == baseline_sha

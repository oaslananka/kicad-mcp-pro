"""Opt-in actual KiCad connector/VBUS power-width routing acceptance.

Keeps user boards untouched. The 0.60 mm VBUS minimum is a *fixture rule*,
not a validated current-carrying capacity or physical manufacturing claim.
"""

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
    reason="Run only on a test host with KiCad's native pcbnew Python and CLI",
)

_NATIVE_BOARD_BUILDER = """
import pcbnew
import sys
from pathlib import Path

dest, library = Path(sys.argv[1]), Path(sys.argv[2])
board = pcbnew.BOARD()
for name in ("VBUS", "GND"):
    board.Add(pcbnew.NETINFO_ITEM(board, name))

for reference, x in (("J1", 10), ("J2", 23)):
    footprint = pcbnew.FootprintLoad(str(library), "PinHeader_1x01_P2.54mm_Vertical")
    assert footprint is not None, reference
    footprint.SetReference(reference)
    board.Add(footprint)
    footprint.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(x), pcbnew.FromMM(10)))
    pads = list(footprint.Pads())
    assert len(pads) == 1 and pads[0].GetNumber() == "1"
    pads[0].SetNet(board.FindNet("VBUS"))

for a, z in (((0, 0), (34, 0)), ((34, 0), (34, 22)),
             ((34, 22), (0, 22)), ((0, 22), (0, 0))):
    edge = pcbnew.PCB_SHAPE(board)
    edge.SetShape(pcbnew.SHAPE_T_SEGMENT)
    edge.SetStart(pcbnew.VECTOR2I(pcbnew.FromMM(a[0]), pcbnew.FromMM(a[1])))
    edge.SetEnd(pcbnew.VECTOR2I(pcbnew.FromMM(z[0]), pcbnew.FromMM(z[1])))
    edge.SetLayer(pcbnew.Edge_Cuts)
    edge.SetWidth(pcbnew.FromMM(0.05))
    board.Add(edge)

obstacle = pcbnew.PCB_TRACK(board)
obstacle.SetStart(pcbnew.VECTOR2I(pcbnew.FromMM(16), pcbnew.FromMM(10)))
obstacle.SetEnd(pcbnew.VECTOR2I(pcbnew.FromMM(17), pcbnew.FromMM(10)))
obstacle.SetWidth(pcbnew.FromMM(0.5))
obstacle.SetLayer(pcbnew.F_Cu)
obstacle.SetNet(board.FindNet("GND"))
board.Add(obstacle)
pcbnew.SaveBoard(str(dest), board)

reopened = pcbnew.LoadBoard(str(dest))
assert reopened is not None
assert {f.GetReference() for f in reopened.GetFootprints()} == {"J1", "J2"}
tracks = list(reopened.GetTracks())
assert len(tracks) == 1 and tracks[0].GetNetname() == "GND"
"""

_VBUS_RULE = """(version 1)
(rule "VBUS scenario minimum width"
 (condition "A.NetName == 'VBUS'")
 (constraint track_width (min 0.6000mm))
 (severity error))
"""


def test_native_connector_vbus_width_and_foreign_net_clearance(tmp_path: Path) -> None:
    """Real two-header, other-net obstacle, widths and connectivity DRC."""
    cli = get_config().kicad_cli
    native_python = cli.parent / ("python.exe" if cli.suffix.lower() == ".exe" else "python3")
    footprints = (
        cli.parent.parent / "share" / "kicad" / "footprints" / "Connector_PinHeader_2.54mm.pretty"
    )
    if (
        not cli.is_file()
        or not native_python.is_file()
        or not (footprints / "PinHeader_1x01_P2.54mm_Vertical.kicad_mod").is_file()
    ):
        pytest.skip("Native KiCad and standard one-pin connector library unavailable")

    source = (
        Path(__file__).resolve().parents[1]
        / "fixtures"
        / "benchmark_projects"
        / "fail_dirty_transfer_wrong_pad_nets"
        / "demo.kicad_pro"
    )
    project = tmp_path / "demo.kicad_pro"
    shutil.copy2(source, project)
    rules = tmp_path / "demo.kicad_dru"
    rules.write_text(_VBUS_RULE, encoding="utf-8")
    assert not rules.read_bytes().startswith(b"\xef\xbb\xbf")

    pcb = tmp_path / "demo.kicad_pcb"
    built = subprocess.run(
        [str(native_python), "-c", _NATIVE_BOARD_BUILDER, str(pcb), str(footprints)],
        capture_output=True,
        text=True,
        timeout=45,
        check=False,
    )
    assert built.returncode == 0, built.stderr[-1200:]
    source_hash = hashlib.sha256(pcb.read_bytes()).hexdigest()
    source_project_hash = hashlib.sha256(project.read_bytes()).hexdigest()
    source_rules_hash = hashlib.sha256(rules.read_bytes()).hexdigest()

    def detour(width_mm: float) -> list[TrackSpec]:
        return [
            TrackSpec(10, 10, 11.5, 8.5, "F_Cu", width_mm, "VBUS"),
            TrackSpec(11.5, 8.5, 21.5, 8.5, "F_Cu", width_mm, "VBUS"),
            TrackSpec(21.5, 8.5, 23, 10, "F_Cu", width_mm, "VBUS"),
        ]

    thin = run_route_drc_preflight(
        pcb.read_text(encoding="utf-8"),
        detour(0.25),
        project_file=project,
        kicad_cli=cli,
    )
    assert thin["accepted"] is False
    assert thin["introducedViolations"] >= 1
    assert thin["unconnectedBefore"] == 1

    sufficient = run_route_drc_preflight(
        pcb.read_text(encoding="utf-8"),
        detour(0.70),
        project_file=project,
        kicad_cli=cli,
    )
    assert sufficient == {
        "accepted": True,
        "introducedViolations": 0,
        "unconnectedBefore": 1,
        "unconnectedAfter": 0,
    }
    assert hashlib.sha256(pcb.read_bytes()).hexdigest() == source_hash
    assert hashlib.sha256(project.read_bytes()).hexdigest() == source_project_hash
    assert hashlib.sha256(rules.read_bytes()).hexdigest() == source_rules_hash

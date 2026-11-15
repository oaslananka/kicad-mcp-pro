"""Standalone KiCad-bundled Python adapter for a disposable DRC candidate.

Only call this with a temporary PCB copy. This script runs inside the KiCad
installation's own Python, so the MCP server does not import pcbnew/SWIG.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pcbnew  # type: ignore[import-not-found]  # Only in KiCad-bundled Python.


def main() -> None:
    if len(sys.argv) != 4:
        raise RuntimeError("Expected baseline PCB, disposable candidate PCB and JSON file")
    baseline_file, candidate_file, spec_file = (Path(value) for value in sys.argv[1:4])
    if not all(path.is_file() for path in (baseline_file, candidate_file, spec_file)):
        raise RuntimeError("Missing disposable candidate inputs")
    specs = json.loads(spec_file.read_text(encoding="utf-8"))
    if not isinstance(specs, list) or not 1 <= len(specs) <= 128:
        raise RuntimeError("Unsupported number of candidate segments")

    board = pcbnew.LoadBoard(str(baseline_file))
    before = len(list(board.GetTracks()))
    # The same native Board instance provides stable UUIDs for the baseline and
    # candidate. Loading the two files independently can randomly assign IDs
    # to legacy fixtures with no UUIDs and produce false DRC regressions.
    pcbnew.SaveBoard(str(baseline_file), board)
    for spec in specs:
        net = board.FindNet(spec["net_name"])
        if net is None:
            raise RuntimeError("Candidate net not present on the board")
        layer = getattr(pcbnew, spec["layer"], None)
        if layer is None or not pcbnew.IsCopperLayer(layer):
            raise RuntimeError("Candidate does not use a valid copper layer")
        track = pcbnew.PCB_TRACK(board)
        track.SetStart(pcbnew.VECTOR2I(pcbnew.FromMM(spec["x1_mm"]), pcbnew.FromMM(spec["y1_mm"])))
        track.SetEnd(pcbnew.VECTOR2I(pcbnew.FromMM(spec["x2_mm"]), pcbnew.FromMM(spec["y2_mm"])))
        track.SetLayer(layer)
        track.SetWidth(pcbnew.FromMM(spec["width_mm"]))
        track.SetNet(net)
        board.Add(track)
    pcbnew.SaveBoard(str(candidate_file), board)

    reopened = pcbnew.LoadBoard(str(candidate_file))
    if len(list(reopened.GetTracks())) != before + len(specs):
        raise RuntimeError("Disposable board readback failed")
    print("NATIVE_PREFLIGHT_SAVED_REOPENED", len(specs))


if __name__ == "__main__":
    main()

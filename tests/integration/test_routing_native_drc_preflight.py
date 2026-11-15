"""Opt-in real KiCad CLI/SWIG routing DRC acceptance on a disposable fixture."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from kicad_mcp.config import get_config
from kicad_mcp.pcb.route_drc_preflight import RoutePreflightError, run_route_drc_preflight
from kicad_mcp.routing.differential_pair_rules import build_differential_pair_rule
from kicad_mcp.routing.manual_tracks import TrackSpec

pytestmark = pytest.mark.skipif(
    os.environ.get("KICAD_MCP_RUN_ROUTING_NATIVE_PREFLIGHT") != "1",
    reason="Only run on an authorized KiCad host with native PCB Python and CLI",
)


_NATIVE_NORMALIZE = """
import pcbnew
import sys
board = pcbnew.LoadBoard(sys.argv[1])
assert board is not None
pcbnew.SaveBoard(sys.argv[1], board)
assert pcbnew.LoadBoard(sys.argv[1]) is not None
"""


def _run_native_python(native_python: Path, snippet: str, *arguments: Path) -> None:
    """Only execute fixed test-controlled KiCad snippets on disposable files."""
    result = subprocess.run(
        [str(native_python), "-c", snippet, *(str(path) for path in arguments)],
        capture_output=True,
        text=True,
        timeout=40,
        check=False,
        shell=False,
    )
    assert result.returncode == 0, result.stderr[-1200:]


def _canonical_ipc_fixture(tmp_path: Path, source: Path, native_python: Path) -> str:
    """Normalize a copied legacy fixture as the live KiCad IPC snapshot does."""
    disposable = tmp_path / "demo.kicad_pcb"
    shutil.copy2(source, disposable)
    _run_native_python(native_python, _NATIVE_NORMALIZE, disposable)
    snapshot = disposable.read_text(encoding="utf-8")
    assert '(uuid "' in snapshot
    return snapshot


def test_native_preflight_accepts_connected_route_but_rejects_new_shorts(tmp_path: Path) -> None:
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
    native_python = cli.parent / "python.exe"
    if not cli.is_file() or not native_python.is_file():
        pytest.skip("KiCad-bundled native Python/CLI not installed")

    shutil.copy2(project, tmp_path / "demo.kicad_pro")
    snapshot = _canonical_ipc_fixture(tmp_path, pcb, native_python)
    project = tmp_path / "demo.kicad_pro"

    good = run_route_drc_preflight(
        snapshot,
        [TrackSpec(10.95, 10, 19.05, 10, "F_Cu", 0.25, "MID")],
        project_file=project,
        kicad_cli=cli,
    )
    bad = run_route_drc_preflight(
        snapshot,
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
    _run_native_python(native_python, native_conversion, pcb)

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


def test_native_custom_track_width_rules_cannot_be_silently_skipped(
    tmp_path: Path,
) -> None:
    source = (
        Path(__file__).resolve().parents[1]
        / "fixtures"
        / "benchmark_projects"
        / "fail_dirty_transfer_wrong_pad_nets"
    )
    pro = tmp_path / "demo.kicad_pro"
    shutil.copy2(source / "demo.kicad_pro", pro)
    rules_file = tmp_path / "demo.kicad_dru"
    valid_rule = (
        "(version 1)\n"
        '(rule "MID min power trace"\n'
        "  (condition \"A.NetName == 'MID'\")\n"
        "  (constraint track_width (min 0.6000mm))\n"
        "  (severity error)\n"
        ")\n"
    )
    rules_file.write_text(valid_rule, encoding="utf-8")
    cli = get_config().kicad_cli
    native_python = cli.parent / "python.exe"
    if not cli.is_file() or not native_python.is_file():
        pytest.skip("KiCad native Python/CLI not available")
    pcb_text = _canonical_ipc_fixture(tmp_path, source / "demo.kicad_pcb", native_python)

    too_thin = run_route_drc_preflight(
        pcb_text,
        [TrackSpec(10.95, 10, 19.05, 10, "F_Cu", 0.25, "MID")],
        project_file=pro,
        kicad_cli=cli,
    )
    safe_width = run_route_drc_preflight(
        pcb_text,
        [TrackSpec(10.95, 10, 19.05, 10, "F_Cu", 0.70, "MID")],
        project_file=pro,
        kicad_cli=cli,
    )
    assert too_thin["accepted"] is False
    assert too_thin["introducedViolations"] >= 1
    assert safe_width["accepted"] is True

    # The KiCad CLI may return exit 0 when a malformed .kicad_dru is ignored.
    rules_file.write_text(
        "(rules\n"
        '(rule "MID min power trace" (condition "A.NetName == \'MID\'")\n'
        " (constraint track_width (min 0.6000mm)) (severity error))\n"
        ")\n",
        encoding="utf-8",
    )
    _checked_args = (pcb_text, [TrackSpec(10.95, 10, 19.05, 10, "F_Cu", 0.25, "MID")])
    _checked_kwargs = {"project_file": pro, "kicad_cli": cli}
    with pytest.raises(RoutePreflightError, match="custom.*rule|rule.*load"):
        run_route_drc_preflight(*_checked_args, **_checked_kwargs)


def test_native_usb_differential_pair_matched_skew_passes_and_mismatch_fails(
    tmp_path: Path,
) -> None:
    """KiCad's native pair-skew DRC is a separate gate from connectivity."""
    source = (
        Path(__file__).resolve().parents[1]
        / "fixtures"
        / "benchmark_projects"
        / "fail_dirty_transfer_wrong_pad_nets"
    )
    original_pcb = source / "demo.kicad_pcb"
    original_sha = hashlib.sha256(original_pcb.read_bytes()).hexdigest()
    board = tmp_path / "demo.kicad_pcb"
    shutil.copy2(original_pcb, board)
    shutil.copy2(source / "demo.kicad_pro", tmp_path / "demo.kicad_pro")
    rule_name, body = build_differential_pair_rule("USB_D_P", "USB_D_N", 0.25, 0.5, 0.1)
    (tmp_path / "demo.kicad_dru").write_text("(version 1)\n" + body + "\n", encoding="utf-8")
    cli = get_config().kicad_cli
    native_python = cli.parent / "python.exe"
    if not cli.is_file() or not native_python.is_file():
        pytest.skip("Native KiCad Python and CLI unavailable")
    fixture_builder = """
import pcbnew
import sys
from pathlib import Path

root = Path(sys.argv[1])
board_file = root / "demo.kicad_pcb"
b = pcbnew.LoadBoard(str(board_file))
assert b is not None
nets = {}
for name in ("USB_D_P", "USB_D_N"):
    net = pcbnew.NETINFO_ITEM(b, name)
    b.Add(net)
    nets[name] = net
pads = {
    ("R1", "2"): ("USB_D_P", 10.95, 8.5),
    ("R2", "1"): ("USB_D_P", 19.05, 8.5),
    ("R1", "1"): ("USB_D_N", 10.95, 9.25),
    ("R2", "2"): ("USB_D_N", 19.05, 9.25),
}
seen = set()
for fp in b.GetFootprints():
    for pad in fp.Pads():
        key = (fp.GetReference(), pad.GetNumber())
        if key not in pads:
            continue
        net, x, y = pads[key]
        pad.SetNet(nets[net])
        pad.SetSize(pcbnew.VECTOR2I(pcbnew.FromMM(.45), pcbnew.FromMM(.45)))
        pad.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(x), pcbnew.FromMM(y)))
        seen.add(key)
assert seen == set(pads)
pcbnew.SaveBoard(str(board_file), b)

for mode in ("matched", "mismatched"):
    design = pcbnew.LoadBoard(str(board_file))
    assert design is not None

    def add_track(net_name, x1, y1, x2, y2):
        track = pcbnew.PCB_TRACK(design)
        track.SetStart(pcbnew.VECTOR2I(pcbnew.FromMM(x1), pcbnew.FromMM(y1)))
        track.SetEnd(pcbnew.VECTOR2I(pcbnew.FromMM(x2), pcbnew.FromMM(y2)))
        track.SetLayer(pcbnew.F_Cu)
        track.SetWidth(pcbnew.FromMM(.25))
        track.SetNet(design.FindNet(net_name))
        design.Add(track)

    add_track("USB_D_P", 10.95, 8.5, 19.05, 8.5)
    negative = [(10.95, 9.25), (19.05, 9.25)]
    if mode == "mismatched":
        negative = [
            (10.95, 9.25), (14, 9.25), (15, 10.25),
            (16, 9.25), (19.05, 9.25),
        ]
    for a, z in zip(negative, negative[1:]):
        add_track("USB_D_N", *a, *z)

    output = root / mode
    output.mkdir()
    for extension in ("pro", "dru"):
        (output / f"demo.kicad_{extension}").write_bytes(
            (root / f"demo.kicad_{extension}").read_bytes()
        )
    pcbnew.SaveBoard(str(output / "demo.kicad_pcb"), design)
"""
    result = subprocess.run(
        [str(native_python), "-c", fixture_builder, str(tmp_path)],
        capture_output=True,
        text=True,
        timeout=45,
        check=False,
    )
    assert result.returncode == 0, result.stderr[-1200:]
    preflight = run_route_drc_preflight(
        board.read_text(encoding="utf-8"),
        [
            TrackSpec(10.95, 8.5, 19.05, 8.5, "F_Cu", 0.25, "USB_D_P"),
            TrackSpec(10.95, 9.25, 19.05, 9.25, "F_Cu", 0.25, "USB_D_N"),
        ],
        project_file=tmp_path / "demo.kicad_pro",
        kicad_cli=cli,
        pair_nets=frozenset(("USB_D_P", "USB_D_N")),
    )
    assert preflight["accepted"] is True
    assert preflight["introducedViolations"] == 0
    assert preflight["unconnectedBefore"] == 2
    assert preflight["unconnectedAfter"] == 0

    for mode, should_violate in (("matched", False), ("mismatched", True)):
        case = tmp_path / mode
        report = case / "report.json"
        result = subprocess.run(
            [
                str(cli),
                "pcb",
                "drc",
                "--format",
                "json",
                "--output",
                str(report),
                str(case / "demo.kicad_pcb"),
            ],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        assert result.returncode == 0, result.stderr[-1000:]
        findings = json.loads(report.read_text(encoding="utf-8"))
        skew_errors = [
            entry
            for entry in findings["violations"]
            if entry.get("type") == "skew_out_of_range"
            and rule_name in entry.get("description", "")
        ]
        assert bool(skew_errors) is should_violate
        assert len(findings["unconnected_items"]) == 0

    assert hashlib.sha256(original_pcb.read_bytes()).hexdigest() == original_sha

"""Native mounting-hole rule-area acceptance for issue #1963."""

from __future__ import annotations

import json
import os
import re
import shutil
import uuid
from pathlib import Path

import pytest

from kicad_mcp.config import reset_config
from kicad_mcp.routing.path_planner import _point_in_ring
from kicad_mcp.server import build_server
from kicad_mcp.tools.export_support import _run_cli
from kicad_mcp.tools.pcb import _replace_root_at
from kicad_mcp.utils.sexpr import iter_root_children
from tests.conftest import call_tool_text

FIXTURE = Path(__file__).resolve().parents[2] / "packages/kicad-fixtures/fixtures/empty-board"


def _probe(kind: str, x: float, y: float) -> str:
    if kind == "track":
        return (
            f"(segment (start {x} {y}) (end {x} {y + 0.5}) (width 0.25) "
            f'(layer "F.Cu") (net 0) (uuid "{uuid.uuid4()}"))'
        )
    if kind == "via":
        return (
            f"(via (at {x} {y}) (size 0.6) (drill 0.3) "
            f'(layers "F.Cu" "B.Cu") (net 0) (uuid "{uuid.uuid4()}"))'
        )
    body = (
        '(pad "1" smd circle (at 0 0) (size 0.5 0.5) (layers "F.Cu" "F.Paste" "F.Mask"))'
        if kind == "pad"
        else "(fp_rect (start -0.3 -0.3) (end 0.3 0.3) "
        '(stroke (width 0.05) (type solid)) (fill none) (layer "F.CrtYd")) '
        "(fp_rect (start -0.2 -0.2) (end 0.2 0.2) "
        '(stroke (width 0.1) (type solid)) (fill none) (layer "F.Fab"))'
    )
    return (
        f'(footprint "Probe" (layer "F.Cu") (uuid "{uuid.uuid4()}") (at {x} {y} 0) '
        '(property "Reference" "X1" (at 0 -2 0) (layer "F.SilkS") '
        "(effects (font (size 1 1) (thickness 0.15)))) "
        '(property "Value" "Probe" (at 0 2 0) (layer "F.Fab") '
        "(effects (font (size 1 1) (thickness 0.15)))) (attr board_only) "
        f"{body})"
    )


def _drc_types(board: Path, report: Path, *flags: str) -> list[str]:
    report.unlink(missing_ok=True)
    code, stdout, stderr = _run_cli(
        "pcb",
        "drc",
        "--format",
        "json",
        "--severity-all",
        "--exit-code-violations",
        *flags,
        "--output",
        str(report),
        str(board),
    )
    assert report.is_file(), stderr or stdout
    assert code in {0, 5}, stderr or stdout
    data = json.loads(report.read_text(encoding="utf-8"))
    return [item["type"] for item in data["violations"]]


def _net_pad(reference: str, x: float, y: float) -> str:
    return (
        f'(footprint "ProbeGround" (layer "F.Cu") (uuid "{uuid.uuid4()}") (at {x} {y} 0) '
        f'(property "Reference" "{reference}" (at 0 -2 0) (layer "F.SilkS") '
        "(effects (font (size 1 1) (thickness 0.15)))) "
        '(property "Value" "ProbeGround" (at 0 2 0) (layer "F.Fab") '
        "(effects (font (size 1 1) (thickness 0.15)))) (attr through_hole board_only) "
        '(pad "1" thru_hole circle (at 0 0) (size 2 2) (drill 0.8) '
        '(layers "*.Cu" "*.Mask") (net 1 "GND")))'
    )


def _pour(layer: str) -> str:
    return (
        f'(zone (net 1) (net_name "GND") (layer "{layer}") (uuid "{uuid.uuid4()}") '
        "(hatch edge 0.5) (connect_pads (clearance 0.3)) (min_thickness 0.25) "
        "(fill yes (thermal_gap 0.3) (thermal_bridge_width 0.3) "
        "(island_removal_mode 0) (island_area_min 0)) "
        "(polygon (pts (xy 3 3) (xy 97 3) (xy 97 57) (xy 3 57))))"
    )


def _append_objects(board: Path, baseline: str, *objects: str) -> None:
    board.write_text(baseline.rstrip()[:-1] + "\n".join(objects) + "\n)\n", encoding="utf-8")


def _assert_native_pour_policy(board: Path, report: Path, baseline: str, allow: bool) -> None:
    _append_objects(
        board, baseline, '(net 1 "GND")', _net_pad("J1", 50, 30), _pour("F.Cu"), _pour("B.Cu")
    )
    assert _drc_types(board, report, "--refill-zones", "--save-board") == []
    observed: set[str] = set()
    for name, zone in iter_root_children(board.read_text(encoding="utf-8")):
        if name != "zone":
            continue
        layer = next(value for key, value in iter_root_children(zone) if key == "layer")
        observed.add(layer)
        polygons = [
            tuple((float(x), float(y)) for x, y in re.findall(r"\(xy ([-\d.]+) ([-\d.]+)\)", fill))
            for kind, fill in iter_root_children(zone)
            if kind == "filled_polygon"
        ]
        assert polygons
        assert any(_point_in_ring((12.8, 10), points) for points in polygons) is allow
        assert any(_point_in_ring((35, 30), points) for points in polygons)
        assert not any(_point_in_ring((10, 10), points) for points in polygons)
    assert observed == {'(layer "F.Cu")', '(layer "B.Cu")'}


def _assert_native_hole_clearance(board: Path, report: Path, baseline: str) -> None:
    # A connected copper track makes the physical hole clearance check non-vacuous.
    for y, expected in ((10.0, True), (11.8, True), (15.0, False)):
        _append_objects(
            board,
            baseline,
            '(net 1 "GND")',
            _net_pad("J1", 4, y),
            _net_pad("J2", 20, y),
            f"(segment (start 4 {y}) (end 20 {y}) (width 0.25) "
            f'(layer "F.Cu") (net 1) (uuid "{uuid.uuid4()}"))',
        )
        assert ("hole_clearance" in _drc_types(board, report, "--all-track-errors")) is expected


def _assert_native_file_placement(board: Path, report: Path, baseline: str) -> None:
    block = next(
        value
        for key, value in iter_root_children(baseline)
        if key == "footprint" and '(property "Reference" "H1"' in value
    )
    moved = baseline.replace(block, _replace_root_at(block, x_mm=25, y_mm=20, rotation=90), 1)
    board.write_text(moved, encoding="utf-8")
    code, stdout, stderr = _run_cli("pcb", "upgrade", "--force", str(board))
    assert code == 0, stderr or stdout
    moved = board.read_text(encoding="utf-8")
    assert _drc_types(board, report) == []
    for x, y, expected in ((27.8, 20, True), (12.8, 10, False)):
        _append_objects(board, moved, _probe("track", x, y))
        assert ("items_not_allowed" in _drc_types(board, report)) is expected


@pytest.mark.anyio
@pytest.mark.parametrize("allow_pours", [True, False])
async def test_native_mounting_hole_keepout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, allow_pours: bool
) -> None:
    configured = os.environ.get("KICAD_NATIVE_MOUNTING_HOLE_CLI")
    if not configured:
        pytest.skip("Explicit native KiCad mounting-hole executable required")
    cli = Path(configured).resolve(strict=True)
    assert cli.is_file()
    project = tmp_path / "project"
    project.mkdir()
    sources = tuple(FIXTURE.glob("*.kicad_*"))
    original = {source: source.read_bytes() for source in sources}
    for source in sources:
        shutil.copy2(source, project / source.name)
    board = project / "empty-board.kicad_pcb"
    for key, value in {
        "KICAD_CONFIG_HOME": str(tmp_path / "config"),
        "KICAD_DOCUMENTS_HOME": str(tmp_path / "documents"),
        "KICAD_MCP_KICAD_CLI": str(cli),
        "KICAD_MCP_PROJECT_DIR": str(project),
        "KICAD_MCP_WORKSPACE_ROOT": str(project),
        "KICAD_MCP_KICAD_SOCKET_PATH": str(tmp_path / "unbound.sock"),
        "KICAD_MCP_OPERATING_MODE": "write",
        # Isolated native contract test; production runtime filtering is unchanged.
        "KICAD_MCP_FILTER_RUNTIME_TOOLS": "false",
    }.items():
        monkeypatch.setenv(key, value)
    reset_config()
    code, version, error = _run_cli("version")
    assert code == 0, error
    assert version.strip().startswith("10."), version
    server = build_server("full")
    result = await call_tool_text(
        server,
        "pcb_add_mounting_holes",
        {
            "clearance_mm": 1.9,
            "margin_mm": 10,
            "keepout": True,
            "keepout_allow_pours": allow_pours,
            "hole_clearance_mm": 0.5,
        },
    )
    assert "Added 4 mounting hole(s)" in result, result
    code, stdout, stderr = _run_cli("pcb", "upgrade", "--force", str(board))
    assert code == 0, stderr or stdout
    baseline = board.read_text(encoding="utf-8")
    assert baseline.count('(layers "*.Mask")') == 4
    assert baseline.count("(drill 3.2)") == 4
    assert baseline.count("(pads not_allowed)") == 4
    assert baseline.count("(tracks not_allowed)") == 4
    assert baseline.count("(vias not_allowed)") == 4
    assert baseline.count("(footprints not_allowed)") == 4
    pour_rule = "(copperpour allowed)" if allow_pours else "(copperpour not_allowed)"
    assert baseline.count(pour_rule) == 4
    report = project / "drc.json"
    assert _drc_types(board, report) == []
    for kind in ("pad", "track", "via", "footprint"):
        for inside in (True, False):
            x, y = (12.8, 10.0) if inside else (35.0, 30.0)
            _append_objects(board, baseline, _probe(kind, x, y))
            types = _drc_types(board, report)
            assert ("items_not_allowed" in types) is inside, (kind, inside, types)
    board.write_text(baseline, encoding="utf-8")
    drill = project / "drill"
    drill.mkdir()
    code, stdout, stderr = _run_cli(
        "pcb",
        "export",
        "drill",
        "--format",
        "excellon",
        "--excellon-separate-th",
        "--output",
        str(drill) + os.sep,
        str(board),
    )
    assert code == 0, stderr or stdout
    npth = (drill / "empty-board-NPTH.drl").read_text(encoding="utf-8")
    assert "T1C3.200" in npth
    assert {line for line in npth.splitlines() if line.startswith("X")} == {
        "X10.0Y-10.0",
        "X10.0Y-50.0",
        "X90.0Y-10.0",
        "X90.0Y-50.0",
    }
    _assert_native_pour_policy(board, report, baseline, allow_pours)
    _assert_native_hole_clearance(board, report, baseline)
    _assert_native_file_placement(board, report, baseline)
    assert {source: source.read_bytes() for source in sources} == original

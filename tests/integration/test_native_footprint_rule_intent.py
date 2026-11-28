"""Opt-in native KiCad acceptance of footprint-owned rule-layer intent (#1947)."""

from __future__ import annotations

import json
import os
import re
import uuid
from pathlib import Path

import pytest

from kicad_mcp.config import reset_config
from kicad_mcp.connection import reset_connection
from kicad_mcp.pcb.rule_layer_intent import FIELD
from kicad_mcp.routing.path_planner import _point_in_ring
from kicad_mcp.server import build_server
from kicad_mcp.tools import pcb
from kicad_mcp.tools.export_support import _run_cli
from kicad_mcp.utils.sexpr import iter_root_children
from tests.conftest import tool_text
from tests.integration.test_native_mounting_hole_keepout import _append_objects, _net_pad, _pour
from tests.unit.test_pcb_keepout_layer_intent import _stackup

FIXTURE = Path(__file__).resolve().parents[2] / "packages/kicad-fixtures/fixtures/empty-board"
COPPER = ["F.Cu", "In1.Cu", "In2.Cu", "In3.Cu", "In4.Cu", "B.Cu"]


def _saved_masks(content: str) -> dict[str, set[str]]:
    result = {}
    for kind, footprint in iter_root_children(content):
        if kind != "footprint":
            continue
        children = list(iter_root_children(footprint))
        reference = next(
            value.split('"')[3]
            for key, value in children
            if key == "property" and value.startswith('(property "Reference"')
        )
        if reference not in {"U1", "U2"}:
            continue
        field = next(
            value
            for key, value in children
            if key == "property" and value.startswith(f'(property "{FIELD}"')
        )
        zone = next(value for key, value in children if key == "zone")
        zone_children = list(iter_root_children(zone))
        identity = next(value.split('"')[1] for key, value in zone_children if key == "uuid")
        assert identity in field
        layers = next(value for key, value in zone_children if key == "layers")
        result[reference] = set(re.findall(r'"([^"]+)"', layers))
    return result


def _assert_track_exclusion(board: Path, report: Path, baseline: str) -> None:
    probes = {}
    segments = []
    for index, layer in enumerate(COPPER):
        for name, x, y in (
            ("all", 18 + index * 2, 17),
            ("fixed", 62 + index * 2, 17),
            ("outside", 18 + index * 2, 49),
        ):
            identity = str(uuid.uuid4())
            probes[identity] = (layer, name)
            segments.append(
                f"(segment (start {x} {y}) (end {x + 1} {y}) (width 0.25) "
                f'(layer "{layer}") (net 0) (uuid "{identity}"))'
            )
    _append_objects(board, baseline, *segments)
    code, stdout, stderr = _run_cli(
        "pcb",
        "drc",
        "--format",
        "json",
        "--severity-all",
        "--exit-code-violations",
        "--output",
        str(report),
        str(board),
    )
    assert code == 5 and report.is_file(), stderr or stdout
    data = json.loads(report.read_text(encoding="utf-8"))
    observed = {
        probes[item["uuid"]]
        for violation in data["violations"]
        if violation["type"] == "items_not_allowed"
        for item in violation["items"]
        if item.get("uuid") in probes
    }
    assert observed == {(layer, "all") for layer in COPPER} | {("F.Cu", "fixed"), ("B.Cu", "fixed")}


def _assert_pour_exclusion(board: Path, report: Path, baseline: str) -> None:
    _append_objects(
        board,
        baseline,
        '(net 1 "GND")',
        _net_pad("J1", 85, 45),
        *[_pour(layer) for layer in COPPER],
    )
    report.unlink(missing_ok=True)
    code, stdout, stderr = _run_cli(
        "pcb",
        "drc",
        "--format",
        "json",
        "--severity-all",
        "--exit-code-violations",
        "--refill-zones",
        "--save-board",
        "--output",
        str(report),
        str(board),
    )
    assert code in {0, 5} and report.is_file(), stderr or stdout
    observed = {}
    for kind, zone in iter_root_children(board.read_text(encoding="utf-8")):
        if kind != "zone":
            continue
        layer = next(value for key, value in iter_root_children(zone) if key == "layer").split('"')[
            1
        ]
        polygons = [
            tuple((float(x), float(y)) for x, y in re.findall(r"\(xy ([-\d.]+) ([-\d.]+)\)", fill))
            for key, fill in iter_root_children(zone)
            if key == "filled_polygon"
        ]
        assert polygons, layer
        observed[layer] = tuple(
            any(_point_in_ring(point, points) for points in polygons)
            for point in ((28, 17), (72, 17), (80, 45))
        )
    assert set(observed) == set(COPPER)
    for layer, (all_inside, fixed_inside, outside) in observed.items():
        assert not all_inside
        assert fixed_inside is (layer not in {"F.Cu", "B.Cu"})
        assert outside


@pytest.mark.anyio
async def test_native_footprint_keepouts_follow_explicit_layer_intent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cli = os.environ.get("KICAD_NATIVE_KEEPOUT_CLI")
    library = os.environ.get("KICAD_NATIVE_KEEPOUT_FOOTPRINT")
    if not cli or not library:
        pytest.skip("Explicit native KiCad CLI and stock ESP32-C6-MINI-1 footprint required")
    executable = Path(cli).resolve(strict=True)
    stock = Path(library).resolve(strict=True)
    assert executable.is_file() and stock.is_file()
    original = stock.read_bytes()
    fixture = FIXTURE / "empty-board.kicad_pcb"
    fixture_bytes = fixture.read_bytes()
    project = tmp_path / "project"
    project.mkdir()
    board = project / "probe.kicad_pcb"
    board.with_suffix(".kicad_pro").write_text("{}\n", encoding="utf-8")
    fixed = tmp_path / "fixed.kicad_mod"
    pattern = r'\(layers\s+"F\.Cu"\s+"B\.Cu"\s+"In1\.Cu"[\s\S]*?"In30\.Cu"\s*\)'
    restricted, count = re.subn(
        pattern, '(layers "F.Cu" "B.Cu")', stock.read_text(encoding="utf-8"), count=1
    )
    assert count == 1
    fixed.write_text(restricted, encoding="utf-8")
    for name in tuple(os.environ):
        if name.startswith(("KICAD_MCP_", "KICAD_API_")):
            monkeypatch.delenv(name)
    for key, value in {
        "KICAD_CONFIG_HOME": str(tmp_path / "config"),
        "KICAD_DOCUMENTS_HOME": str(tmp_path / "documents"),
        "KICAD_MCP_KICAD_CLI": str(executable),
        "KICAD_MCP_PROJECT_DIR": str(project),
        "KICAD_MCP_WORKSPACE_ROOT": str(project),
        "KICAD_MCP_KICAD_SOCKET_PATH": str(tmp_path / "unbound.sock"),
        "KICAD_MCP_OPERATING_MODE": "write",
        "KICAD_MCP_FILTER_RUNTIME_TOOLS": "false",
        "KICAD_MCP_TELEMETRY_ENABLED": "false",
    }.items():
        monkeypatch.setenv(key, value)
    reset_config()
    reset_connection()
    version_code, version, error = _run_cli("version")
    assert version_code == 0 and version.strip().startswith("10."), error or version
    monkeypatch.setattr(
        pcb, "_footprint_file", lambda _lib, name: stock if name == "ESP32-C6-MINI-1" else fixed
    )
    all_area = pcb._render_board_footprint_block(
        "RF_Module:ESP32-C6-MINI-1",
        reference="U1",
        value="RF",
        x_mm=28,
        y_mm=35,
        rotation=0,
        pad_nets={},
    )
    fixed_area = pcb._render_board_footprint_block(
        "RF_Module:Fixed",
        reference="U2",
        value="RF",
        x_mm=72,
        y_mm=35,
        rotation=0,
        pad_nets={},
    )
    _append_objects(
        board, fixture.read_text(encoding="utf-8"), all_area, pcb._refresh_uuid_fields(fixed_area)
    )
    server = build_server("full")
    for layer_count in (2, 4, 2, 4, 6):
        result = await server.call_tool(
            "pcb_set_stackup", {"layers": [layer.model_dump() for layer in _stackup(layer_count)]}
        )
        assert "Configured stackup" in tool_text(result), tool_text(result)
        code, stdout, stderr = _run_cli("pcb", "upgrade", "--force", str(board))
        assert code == 0, stderr or stdout
        expected = {"F.Cu", "B.Cu", *(f"In{i}.Cu" for i in range(1, layer_count - 1))}
        assert _saved_masks(board.read_text(encoding="utf-8")) == {
            "U1": expected,
            "U2": {"F.Cu", "B.Cu"},
        }
    baseline = board.read_text(encoding="utf-8")
    report = project / "drc.json"
    _assert_track_exclusion(board, report, baseline)
    _assert_pour_exclusion(board, report, baseline)
    assert stock.read_bytes() == original and fixture.read_bytes() == fixture_bytes

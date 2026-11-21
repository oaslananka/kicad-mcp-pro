"""Opt-in native KiCad 10 SVG regression: shaped labels must clear their icon/frame."""

from __future__ import annotations

import math
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from defusedxml.ElementTree import parse

from kicad_mcp.tools.schematic import _terminal_rotation_from_vector, label_block, wire_block

NS = {"svg": "http://www.w3.org/2000/svg"}
DIRECTIONS = ((1, 0), (0, -1), (-1, 0), (0, 1))


def _points(path: str) -> list[tuple[float, float]]:
    values = [float(value) for value in re.findall(r"-?\d+(?:\.\d+)?", path)]
    return list(zip(values[::2], values[1::2], strict=True))


def _polygon_margin(point: tuple[float, float], polygon: list[tuple[float, float]]) -> float:
    edges = list(zip(polygon, polygon[1:] + polygon[:1], strict=True))
    orientation = math.copysign(1, sum(a[0] * b[1] - a[1] * b[0] for a, b in edges))
    px, py = point
    return min(
        orientation * ((bx - ax) * (py - ay) - (by - ay) * (px - ax)) / math.hypot(bx - ax, by - ay)
        for (ax, ay), (bx, by) in edges
    )


def _fixture(kind: str) -> str:
    parts = [
        '(kicad_sch (version 20250316) (generator "kicad-mcp-pro") '
        '(uuid "55400650-1f3c-4147-ac77-8ae27bfdb553") (paper "A4") (lib_symbols)\n'
    ]
    for i, (ux, uy) in enumerate(DIRECTIONS):
        for j, name in enumerate(("EN", "BOOT")):
            x, y = 50.8 * (i + 1), 50.8 * (j + 1)
            parts.append(wire_block(x - 10.16 * ux, y - 10.16 * uy, x, y))
            parts.append(
                label_block(
                    name,
                    x,
                    y,
                    _terminal_rotation_from_vector(ux, uy),
                    kind=kind,
                    shape="bidirectional",
                )
            )
    parts.append('(sheet_instances (path "/" (page "1"))) (embedded_fonts no))')
    return "\n".join(parts)


@pytest.mark.parametrize("kind", ["global_label", "hierarchical_label"])
def test_native_rotated_label_geometry(tmp_path: Path, kind: str) -> None:
    if os.environ.get("KICAD_SVG_NATIVE_ACCEPTANCE") != "1":
        pytest.skip("Explicit native KiCad 10 SVG acceptance only")
    executable = os.environ.get("KICAD_MCP_KICAD_CLI") or shutil.which("kicad-cli")
    assert executable, "Native acceptance requires KiCad CLI"
    source = tmp_path / "rotations.kicad_sch"
    source.write_text(_fixture(kind), encoding="utf-8")
    before = source.read_bytes()
    result = subprocess.run(
        [executable, "sch", "export", "svg", "-o", str(tmp_path) + os.sep, str(source)],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    root = parse(tmp_path / "rotations.svg").getroot()
    count = 0
    for group in root.findall(".//svg:g", NS):
        glyph = group.find("svg:g[@class='stroked-text']", NS)
        frame = group.find("svg:path", NS)
        if glyph is None or frame is None:
            continue
        name = glyph.findtext("svg:desc", namespaces=NS)
        if name not in {"EN", "BOOT"}:
            continue
        polygon = _points(frame.attrib["d"])
        strokes = [
            point for path in glyph.findall("svg:path", NS) for point in _points(path.attrib["d"])
        ]
        assert strokes and len(polygon) >= 4
        x, y = polygon[0]
        column = round(x / 50.8) - 1
        ux, uy = DIRECTIONS[column]
        if kind == "global_label":
            assert min(_polygon_margin(point, polygon) for point in strokes) > 0.2, (name, column)
        else:
            # The hierarchical icon does not enclose its text; its text must
            # be beyond the whole icon along the outward wire direction.
            assert min(px * ux + py * uy for px, py in strokes) > (
                max(px * ux + py * uy for px, py in polygon) + 0.2
            ), (name, column)
        assert (x, y) == pytest.approx((50.8 * (column + 1), 50.8 * (1 if name == "EN" else 2)))
        count += 1
    assert count == 8
    assert source.read_bytes() == before

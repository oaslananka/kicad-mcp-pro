"""Regression: mounting holes can carry a copper keep-out and a hole clearance.

pcb_add_mounting_holes drew the screw-head area as a courtyard only, so nothing
stopped tracks, vias or other footprints from being placed under the screw
head or washer, and there was no way to set the copper clearance to the hole.
Both are now opt-in: ``keepout=True`` adds a footprint rule area on F.Cu and
B.Cu over the courtyard (no tracks, vias, pads or footprints; copper pours as
chosen), and ``hole_clearance_mm`` sets the hole pad's own clearance.
"""

from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from kicad_mcp.server import build_server
from tests.conftest import call_tool_text


def _hole_blocks(pcb_text: str) -> list[str]:
    return [
        block
        for block in re.split(r"\n\t?\(footprint ", pcb_text)[1:]
        if block.startswith('"MountingHole_')
    ]


def _add_outline(project: Path) -> None:
    """Use a real outline for placement, not an invented footprint frame."""
    (project / "demo.kicad_pcb").write_text(
        (
            "(kicad_pcb\n"
            "(version 20250316)\n"
            '(gr_rect (start 0 0) (end 100 80) (layer "Edge.Cuts") (width 0.05))\n'
            ")\n"
        ),
        encoding="utf-8",
    )


@pytest.mark.anyio
@pytest.mark.parametrize("allow_pours", [True, False])
async def test_mounting_holes_can_add_keepout_and_hole_clearance(
    sample_project: Path,
    mock_kicad: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
    allow_pours: bool,
) -> None:
    monkeypatch.setattr("kicad_mcp.tools.pcb._board_is_open", lambda: False)

    _add_outline(sample_project)
    result = await call_tool_text(
        build_server("pcb"),
        "pcb_add_mounting_holes",
        {
            "clearance_mm": 1.9,
            "keepout": True,
            "keepout_allow_pours": allow_pours,
            "hole_clearance_mm": 0.5,
        },
    )

    assert "Added 4 mounting hole(s)" in result, result
    blocks = _hole_blocks((sample_project / "demo.kicad_pcb").read_text(encoding="utf-8"))
    assert len(blocks) == 4
    pour_rule = "(copperpour allowed)" if allow_pours else "(copperpour not_allowed)"
    for block in blocks:
        assert "(zone" in block, block
        zone = block[block.index("(zone") :]
        assert '(layers "F.Cu" "B.Cu")' in zone
        for rule in (
            "(tracks not_allowed)",
            "(vias not_allowed)",
            "(pads not_allowed)",
            "(footprints not_allowed)",
            pour_rule,
        ):
            assert rule in zone, (rule, zone)
        points = [(float(x), float(y)) for x, y in re.findall(r"\(xy ([-\d.]+) ([-\d.]+)\)", zone)]
        # The rule area covers the courtyard circle (radius 1.6 + 1.9 = 3.5 mm).
        assert len(points) >= 16
        assert min((x * x + y * y) ** 0.5 for x, y in points) >= 3.5 - 1e-6
        assert "(clearance 0.5000)" in block


@pytest.mark.anyio
async def test_mounting_holes_default_output_is_unchanged(
    sample_project: Path,
    mock_kicad: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("kicad_mcp.tools.pcb._board_is_open", lambda: False)

    _add_outline(sample_project)
    await call_tool_text(build_server("pcb"), "pcb_add_mounting_holes", {})

    blocks = _hole_blocks((sample_project / "demo.kicad_pcb").read_text(encoding="utf-8"))
    assert len(blocks) == 4
    assert all("(zone" not in block and "(clearance" not in block for block in blocks)


@pytest.mark.anyio
async def test_mounting_holes_refuse_a_board_without_an_outline(
    sample_project: Path,
    mock_kicad: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("kicad_mcp.tools.pcb._board_is_open", lambda: False)
    board = sample_project / "demo.kicad_pcb"
    before = board.read_text(encoding="utf-8")
    result = await call_tool_text(build_server("pcb"), "pcb_add_mounting_holes", {})
    assert "outline" in result.casefold() and "not added" in result.casefold(), result
    assert board.read_text(encoding="utf-8") == before

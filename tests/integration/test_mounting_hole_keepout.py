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


@pytest.mark.anyio
@pytest.mark.parametrize("allow_pours", [True, False])
async def test_mounting_holes_can_add_keepout_and_hole_clearance(
    sample_project: Path,
    mock_kicad: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
    allow_pours: bool,
) -> None:
    monkeypatch.setattr("kicad_mcp.tools.pcb._board_is_open", lambda: False)

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

    await call_tool_text(build_server("pcb"), "pcb_add_mounting_holes", {})

    blocks = _hole_blocks((sample_project / "demo.kicad_pcb").read_text(encoding="utf-8"))
    assert len(blocks) == 4
    assert all("(zone" not in block and "(clearance" not in block for block in blocks)

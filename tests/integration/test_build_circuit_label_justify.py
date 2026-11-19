"""Regression: sch_build_circuit must keep each label's ``justify`` and rotation.

Label inputs to ``sch_build_circuit`` are validated as ``AddLabelInput``, which
accepts ``justify``, but the builder dropped it when it emitted the label, so
labels came out with KiCad's centred default (or the rotation-derived default
for global labels) instead of the requested justification. ``sch_add_label``
and ``sch_add_labels_batch`` already honoured it.
"""

from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from kicad_mcp.server import build_server
from tests.conftest import call_tool_text


def _label_blocks(schematic: str) -> dict[str, str]:
    blocks: dict[str, str] = {}
    for match in re.finditer(
        r'\t\((label|global_label|hierarchical_label) "([^"]+)"\n(.*?)\n\t\)', schematic, re.S
    ):
        blocks[match.group(2)] = match.group(3)
    return blocks


@pytest.mark.anyio
async def test_build_circuit_writes_requested_label_justify_and_rotation(
    sample_project: Path, mock_kicad: MagicMock
) -> None:
    server = build_server("schematic")

    await call_tool_text(
        server,
        "sch_build_circuit",
        {
            "labels": [
                {"name": "LEFT_0", "x_mm": 50.8, "y_mm": 50.8, "justify": "left bottom"},
                {
                    "name": "RIGHT_180",
                    "x_mm": 50.8,
                    "y_mm": 63.5,
                    "rotation": 180,
                    "justify": "right bottom",
                },
                {
                    "name": "UP_90",
                    "x_mm": 76.2,
                    "y_mm": 50.8,
                    "rotation": 90,
                    "justify": "left bottom",
                },
                {
                    "name": "GLOBAL_RIGHT",
                    "x_mm": 101.6,
                    "y_mm": 50.8,
                    "kind": "global_label",
                    "justify": "right",
                },
                {"name": "PLAIN", "x_mm": 101.6, "y_mm": 76.2},
            ]
        },
    )

    blocks = _label_blocks((sample_project / "demo.kicad_sch").read_text(encoding="utf-8"))
    assert "(at 50.8 50.8 0)" in blocks["LEFT_0"]
    assert "(justify left bottom)" in blocks["LEFT_0"], blocks["LEFT_0"]
    assert "(at 50.8 63.5 180)" in blocks["RIGHT_180"]
    assert "(justify right bottom)" in blocks["RIGHT_180"]
    assert "(at 76.2 50.8 90)" in blocks["UP_90"]
    assert "(justify left bottom)" in blocks["UP_90"]
    assert "(justify right)" in blocks["GLOBAL_RIGHT"]
    # No justify requested: unchanged, KiCad's centred default for a local label.
    assert "(justify" not in blocks["PLAIN"]

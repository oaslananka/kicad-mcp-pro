"""Power-like net names without a KiCad power symbol remain connected."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from kicad_mcp.server import build_server
from tests.conftest import call_tool_text


@pytest.mark.anyio
async def test_pin_labels_fall_back_when_power_library_has_no_matching_symbol(
    sample_project: Path,
    mock_kicad: MagicMock,
) -> None:
    server = build_server("schematic")
    added = await call_tool_text(
        server,
        "sch_add_symbol",
        {
            "library": "Device",
            "symbol_name": "R",
            "x_mm": 100,
            "y_mm": 100,
            "reference": "R1",
            "value": "1k",
        },
    )
    assert "The schematic was updated" in added, added
    result = await call_tool_text(
        server,
        "sch_add_pin_labels",
        {
            "connections": [
                {"reference": "R1", "pin": "1", "net": "VCAP1"},
                {"reference": "R1", "pin": "2", "net": "SIG"},
            ]
        },
    )
    assert "Added 2 pin terminal(s)" in result, result
    assert "power symbol 'VCAP1' was not found" not in result, result
    schematic = (sample_project / "demo.kicad_sch").read_text(encoding="utf-8")
    assert '(global_label "VCAP1"' in schematic
    assert '(global_label "SIG"' in schematic
    assert '(symbol "power:VCAP1"' not in schematic

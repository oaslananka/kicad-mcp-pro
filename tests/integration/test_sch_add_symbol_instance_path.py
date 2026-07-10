"""Regression: incrementally added symbols must share the root sheet instance path.

``sch_add_symbol`` derives the instance path from the schematic's root UUID. When
``_extract_uuid`` failed to read that UUID it fell back to a fresh random UUID on
every call, so each symbol landed on a different hierarchical path and KiCad
rendered a blank sheet even though the file parsed. This locks the paths together.
"""

from __future__ import annotations

import re

import pytest

from kicad_mcp.server import build_server
from kicad_mcp.tools.schematic import parse_schematic_file
from tests.conftest import call_tool_text


async def _add_resistor(server: object, ref: str, x: float) -> None:
    await call_tool_text(
        server,
        "sch_add_symbol",
        {
            "library": "Device",
            "symbol_name": "R",
            "x_mm": x,
            "y_mm": 100.0,
            "reference": ref,
            "value": "10k",
        },
    )


@pytest.mark.anyio
async def test_incremental_symbols_share_root_instance_path(sample_project, mock_kicad) -> None:
    server = build_server("schematic")
    sch_file = sample_project / "demo.kicad_sch"

    await _add_resistor(server, "R1", 100.0)
    await _add_resistor(server, "R2", 120.0)
    await _add_resistor(server, "R3", 140.0)

    text = sch_file.read_text(encoding="utf-8")
    root_uuid = parse_schematic_file(sch_file)["uuid"]
    assert root_uuid, "root UUID must be readable for instance paths to be consistent"

    instance_paths = set(re.findall(r'\(path "(/[^"]+)"', text))
    assert instance_paths == {f"/{root_uuid}"}, (
        "every symbol instance must sit on the root sheet path; scattered paths "
        f"render blank in KiCad (got {instance_paths})"
    )

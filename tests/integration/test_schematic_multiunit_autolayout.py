"""Integration regression for automatic layout of KiCad multi-unit symbols."""

from __future__ import annotations

import re

import pytest

from kicad_mcp.server import build_server
from tests.conftest import call_tool_text


@pytest.mark.anyio
async def test_build_circuit_places_all_units_of_one_reference_separately(
    sample_project, mock_kicad
) -> None:
    server = build_server("schematic")
    symbols = [
        {
            "library": "MultiUnit",
            "symbol_name": "DualChild",
            "reference": "U1",
            "unit": unit,
            "value": "DualChild",
            "footprint": "Package_DIP:DIP-8_W7.62mm",
        }
        for unit in (1, 2, 3)
    ]
    symbols.append({"library": "Device", "symbol_name": "R", "reference": "R1", "value": "10k"})
    nets = [
        {
            "name": "AMP_A_IN",
            "connections": [
                {"reference": "U1", "pin": "3"},
                {"reference": "R1", "pin": "1"},
            ],
        },
        {
            "name": "AMP_B_IN",
            "connections": [{"reference": "U1", "pin": "5"}],
        },
        {
            "name": "+5V",
            "connections": [{"reference": "U1", "pin": "8"}],
        },
    ]

    result = await call_tool_text(
        server,
        "sch_build_circuit",
        {"symbols": symbols, "nets": nets, "auto_layout": True, "max_paper": "A4"},
    )
    assert "Applied auto-layout" in result

    schematic = (sample_project / "demo.kicad_sch").read_text(encoding="utf-8")
    instances = re.findall(
        r'\(symbol\s*\(lib_id "MultiUnit:DualChild"\)\s*'
        r"\(at\s+([\d.]+)\s+([\d.]+)\s+[-\d.]+\)",
        schematic,
    )
    assert len(instances) == 3
    assert len(set(instances)) == 3

    listed = await call_tool_text(server, "sch_get_symbols", {})
    assert listed.count("U1 DualChild MultiUnit:DualChild") == 3
    for unit in (1, 2, 3):
        assert f"unit={unit}" in listed

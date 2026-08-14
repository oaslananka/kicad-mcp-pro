"""Regression tests for power-symbol pin labels."""

from __future__ import annotations

import re

import pytest

from kicad_mcp.server import build_server
from tests.conftest import call_tool_text

H = chr(35)
q = chr(34)


def _write_power_lib(sample_project) -> None:
    text = "\n".join(
        [
            "(kicad_symbol_lib (version 20250316) (generator pytest)",
            "  (symbol " + q + "PWR_FLAG" + q,
            "    (property "
            + q
            + "Reference"
            + q
            + " "
            + q
            + H
            + "FLG"
            + q
            + " (id 0) (at 0 -2.54 0))",
            "    (property "
            + q
            + "Value"
            + q
            + " "
            + q
            + "PWR_FLAG"
            + q
            + " (id 1) (at 0 2.54 0))",
            "    (symbol " + q + "PWR_FLAG_0_1" + q,
            "      (pin power_out line (at 0 0 90) (length 0) (name "
            + q
            + "pwr"
            + q
            + ") (number "
            + q
            + "1"
            + q
            + "))",
            "    )",
            "  )",
            ")",
            "",
        ]
    )
    symbols_dir = sample_project.parent / "symbols"
    symbols_dir.mkdir(exist_ok=True)
    (symbols_dir / "power.kicad_sym").write_text(text, encoding="utf-8")


def _first_power_ref(sample_project) -> str:
    schematic = (sample_project / "demo.kicad_sch").read_text(encoding="utf-8")
    pattern = "\\(property " + q + "Reference" + q + " " + q + H + "PWR[^" + q + "\\\\]+" + q
    match = re.search(pattern, schematic)
    assert match is not None
    return match.group(0).split(q)[3]


@pytest.mark.anyio
async def test_pin_labels_accept_power_symbol_references(sample_project, mock_kicad) -> None:
    _write_power_lib(sample_project)
    server = build_server("schematic")
    await call_tool_text(
        server,
        "sch_add_power_symbol",
        {"name": "PWR_FLAG", "x_mm": 30.0, "y_mm": 40.0, "snap_to_grid": False},
    )
    power_ref = _first_power_ref(sample_project)
    result = await call_tool_text(
        server,
        "sch_add_pin_labels",
        {"connections": [{"reference": power_ref, "pin": "1", "net": "FLAG_NET"}]},
    )
    assert f"{power_ref}.1 -> FLAG_NET" in result
    schematic = (sample_project / "demo.kicad_sch").read_text(encoding="utf-8")
    assert "FLAG_NET" in schematic


@pytest.mark.anyio
async def test_pin_labels_emit_hierarchical_labels_with_shape(sample_project, mock_kicad) -> None:
    server = build_server("schematic")
    await call_tool_text(
        server,
        "sch_add_symbol",
        {
            "library": "Extended",
            "symbol_name": "ChildTimer",
            "x_mm": 40.0,
            "y_mm": 40.0,
            "reference": "U1",
            "value": "ChildTimer",
            "footprint": "Package_DIP:DIP-8_W7.62mm",
            "rotation": 0,
        },
    )
    result = await call_tool_text(
        server,
        "sch_add_pin_labels",
        {
            "connections": [{"reference": "U1", "pin": "IN", "net": "SENSE", "shape": "input"}],
            "label_kind": "hierarchical",
        },
    )
    assert "U1.IN -> SENSE" in result
    schematic = (sample_project / "demo.kicad_sch").read_text(encoding="utf-8")
    assert "(hierarchical_label " + q + "SENSE" + q in schematic
    assert "(shape input)" in schematic


@pytest.mark.anyio
async def test_pin_labels_power_symbol_errors_are_specific(sample_project, mock_kicad) -> None:
    _write_power_lib(sample_project)
    server = build_server("schematic")
    await call_tool_text(
        server,
        "sch_add_power_symbol",
        {"name": "PWR_FLAG", "x_mm": 30.0, "y_mm": 40.0, "snap_to_grid": False},
    )
    power_ref = _first_power_ref(sample_project)
    missing = H + "PWR_MISSING"
    result = await call_tool_text(
        server,
        "sch_add_pin_labels",
        {
            "connections": [
                {"reference": missing, "pin": "1", "net": "FLAG_NET"},
                {"reference": power_ref, "pin": "2", "net": "FLAG_NET"},
            ]
        },
    )
    assert f"{missing}.1: reference not found" in result
    assert f"{power_ref}.2: symbol type not supported" in result

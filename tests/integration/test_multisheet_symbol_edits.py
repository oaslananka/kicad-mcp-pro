"""lewisfab #1783: by-reference edits must reach child sheets without switching projects."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from kicad_mcp.server import build_server
from tests.conftest import call_tool_text
from tests.integration.test_child_sheet_instance_paths import _write_hierarchy


async def _put_resistor(server: object, sheet_file: str, reference: str) -> None:
    result = await call_tool_text(
        server,
        "sch_add_symbol",
        {
            "library": "Device",
            "symbol_name": "R",
            "reference": reference,
            "value": "10k",
            "x_mm": 100.0,
            "y_mm": 100.0,
            "sheet_file": sheet_file,
        },
    )
    assert "schematic was updated" in result.lower(), result


@pytest.mark.anyio
async def test_all_by_reference_tools_edit_only_the_actual_child_sheet(
    sample_project: Path, mock_kicad: MagicMock
) -> None:
    power, regulator = _write_hierarchy(sample_project)
    root = sample_project / "demo.kicad_sch"
    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})
    await _put_resistor(server, "power.kicad_sch", "R11")
    root_before = root.read_bytes()
    regulator_before = regulator.read_bytes()

    result = await call_tool_text(
        server,
        "sch_update_properties",
        {"reference": "R11", "field": "Value", "value": "22k"},
    )
    assert "Updated R11.Value" in result, result
    assert '(property "Value" "22k"' in power.read_text(encoding="utf-8")
    assert root.read_bytes() == root_before

    result = await call_tool_text(
        server,
        "sch_modify_property",
        {"reference": "R11", "field": "Value", "value": "33k"},
    )
    assert "Updated R11.Value" in result, result
    assert '(property "Value" "33k"' in power.read_text(encoding="utf-8")

    result = await call_tool_text(
        server,
        "lib_assign_footprint",
        {"reference": "R11", "library": "Resistor_SMD", "footprint": "R_0805"},
    )
    assert "Assigned footprint" in result, result
    assert '(property "Footprint" "Resistor_SMD:R_0805"' in power.read_text(encoding="utf-8")

    result = await call_tool_text(
        server, "sch_set_dnp", {"reference": "R11", "enabled": True, "reason": "no-stuff"}
    )
    assert "DNP" in result, result
    assert "(dnp yes)" in power.read_text(encoding="utf-8")

    result = await call_tool_text(
        server,
        "sch_move_symbol",
        {"reference": "R11", "x_mm": 120.65, "y_mm": 120.65},
    )
    assert "Moved symbol" in result, result
    assert "(at 120.65 120.65" in power.read_text(encoding="utf-8")

    result = await call_tool_text(server, "sch_delete_symbol", {"reference": "R11"})
    assert "Deleted" in result, result
    assert '(property "Reference" "R11"' not in power.read_text(encoding="utf-8")
    assert root.read_bytes() == root_before
    assert regulator.read_bytes() == regulator_before


@pytest.mark.anyio
async def test_duplicate_reference_across_sheets_is_not_mutated(
    sample_project: Path, mock_kicad: MagicMock
) -> None:
    power, regulator = _write_hierarchy(sample_project)
    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})
    await _put_resistor(server, "power.kicad_sch", "R41")
    # Deliberately simulate an existing cross-sheet duplicate from an imported project.
    power_text = power.read_text(encoding="utf-8")
    from kicad_mcp.tools.schematic import _find_placed_symbol_blocks

    block = _find_placed_symbol_blocks(power_text, "R41")[0][0]
    regulator_text = regulator.read_text(encoding="utf-8")
    regulator.write_text(
        regulator_text.replace("	(embedded_fonts no)", block + "\n\t(embedded_fonts no)")
    )
    before = (power.read_bytes(), regulator.read_bytes())
    result = await call_tool_text(
        server,
        "sch_update_properties",
        {"reference": "R41", "field": "Value", "value": "unsafe"},
    )
    assert "ambiguous" in result.lower(), result
    assert before == (power.read_bytes(), regulator.read_bytes())


@pytest.mark.anyio
async def test_annotation_covers_every_child_sheet_and_updates_instances(
    sample_project: Path, mock_kicad: MagicMock
) -> None:
    power, regulator = _write_hierarchy(sample_project)
    root = sample_project / "demo.kicad_sch"
    server = build_server("schematic")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})
    await _put_resistor(server, "demo.kicad_sch", "R31")
    await _put_resistor(server, "power.kicad_sch", "R47")
    await _put_resistor(server, "regulator.kicad_sch", "R82")

    result = await call_tool_text(server, "sch_annotate", {"start_number": 1, "order": "sheet"})
    assert "Annotated 3 symbol(s)" in result, result
    refs: set[str] = set()
    from kicad_mcp.tools.schematic import _find_all_placed_symbol_blocks

    for path in (root, power, regulator):
        content = path.read_text(encoding="utf-8")
        placed = _find_all_placed_symbol_blocks(content)
        assert len(placed) == 1, (path, placed)
        ref = placed[0][3]["reference"]
        assert ref in {"R1", "R2", "R3"}, (path, ref)
        assert f'(reference "{ref}")' in placed[0][0], (path, ref)
        refs.add(ref)
    assert refs == {"R1", "R2", "R3"}

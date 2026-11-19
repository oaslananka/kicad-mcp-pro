"""Reference edits must update the KiCad instance nodes, not just display properties."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from kicad_mcp.server import build_server
from tests.conftest import call_tool_text


async def _add_r(server: object, reference: str, x: float) -> None:
    result = await call_tool_text(
        server,
        "sch_add_symbol",
        {
            "library": "Device",
            "symbol_name": "R",
            "x_mm": x,
            "y_mm": 40.0,
            "reference": reference,
            "value": "10k",
            "snap_to_grid": False,
        },
    )
    assert "updated" in result.casefold(), result


@pytest.mark.anyio
async def test_rename_updates_property_and_current_project_instance(
    sample_project: Path, mock_kicad: MagicMock
) -> None:
    server = build_server("schematic")
    await _add_r(server, "R5", 40.0)
    result = await call_tool_text(
        server, "sch_update_properties", {"reference": "R5", "field": "Reference", "value": "R14"}
    )
    assert "Updated R5.Reference" in result, result
    text = (sample_project / "demo.kicad_sch").read_text(encoding="utf-8")
    assert '(property "Reference" "R14"' in text
    assert '(reference "R14")' in text
    assert '(reference "R5")' not in text


@pytest.mark.anyio
async def test_annotation_updates_instances_for_each_symbol(
    sample_project: Path, mock_kicad: MagicMock
) -> None:
    server = build_server("schematic")
    await _add_r(server, "R5", 40.0)
    await _add_r(server, "R9", 70.0)
    result = await call_tool_text(server, "sch_annotate", {"start_number": 1, "order": "sheet"})
    assert "Annotated 2 symbol(s)" in result, result
    text = (sample_project / "demo.kicad_sch").read_text(encoding="utf-8")
    for ref in ("R1", "R2"):
        assert f'(property "Reference" "{ref}"' in text
        assert f'(reference "{ref}")' in text
    assert '(reference "R5")' not in text
    assert '(reference "R9")' not in text


@pytest.mark.anyio
async def test_auto_annotate_also_updates_instance_references(
    sample_project: Path, mock_kicad: MagicMock
) -> None:
    from kicad_mcp.tools.schematic import run_auto_annotate

    server = build_server("schematic")
    await _add_r(server, "R6", 40.0)
    assert "Auto-annotated 1 symbol(s)" in run_auto_annotate(start_number=2)
    content = (sample_project / "demo.kicad_sch").read_text(encoding="utf-8")
    assert '(property "Reference" "R2"' in content
    assert '(reference "R2")' in content

"""A failed second sheet must not leave a partially-renumbered schematic project."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from kicad_mcp.server import build_server
from kicad_mcp.tools import schematic as schematic_mod
from tests.conftest import call_tool_text
from tests.integration.test_child_sheet_instance_paths import _write_hierarchy


@pytest.mark.anyio
async def test_annotation_restores_first_sheet_if_second_write_fails(
    sample_project: Path,
    mock_kicad: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    power, _ = _write_hierarchy(sample_project)
    root = sample_project / "demo.kicad_sch"
    server = build_server("schematic")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})
    for sheet, ref in (("demo.kicad_sch", "R5"), ("power.kicad_sch", "R9")):
        await call_tool_text(
            server,
            "sch_add_symbol",
            {
                "library": "Device",
                "symbol_name": "R",
                "reference": ref,
                "value": "10k",
                "x_mm": 100,
                "y_mm": 100,
                "sheet_file": sheet,
            },
        )

    before = (root.read_bytes(), power.read_bytes())
    actual_writer = schematic_mod._transactional_write_to_schematic_file
    attempts: list[Path] = []

    def fail_second_file(path: Path, mutator, *, allow_node_loss: bool = False) -> str:
        attempts.append(path)
        if path == power:
            raise OSError("simulated second-sheet write failure")
        return actual_writer(path, mutator, allow_node_loss=allow_node_loss)

    monkeypatch.setattr(schematic_mod, "_transactional_write_to_schematic_file", fail_second_file)
    result = await call_tool_text(server, "sch_annotate", {"start_number": 1})
    assert "simulated second-sheet write failure" in result
    assert root in attempts and power in attempts
    assert (root.read_bytes(), power.read_bytes()) == before

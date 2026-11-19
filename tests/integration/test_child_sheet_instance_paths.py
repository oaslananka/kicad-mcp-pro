"""Regression: symbols written into a child sheet need the hierarchical instance path.

KiCad keys every symbol instance by the sheet path from the top-level schematic:
``/<root uuid>`` on the root sheet, ``/<root uuid>/<sheet uuid>`` one level down,
and so on. The file-backed writers built the path from the UUID of the file they
were editing, so a symbol added to a child sheet got ``/<child file uuid>``. KiCad
then treats that symbol as unannotated in the real hierarchy and can drop
unlabelled nets between it and its neighbours.
"""

from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from mcp.server.mcpserver import MCPServer

from kicad_mcp.server import build_server
from tests.conftest import call_tool_text

ROOT_UUID = "00000000-0000-0000-0000-000000000000"
POWER_SHEET_UUID = "11111111-1111-4111-8111-111111111111"
REGULATOR_SHEET_UUID = "22222222-2222-4222-8222-222222222222"
POWER_FILE_UUID = "33333333-3333-4333-8333-333333333333"
REGULATOR_FILE_UUID = "44444444-4444-4444-8444-444444444444"

_PATH = re.compile(r'\(path "(/[^"]*)"')


def _sheet_block(name: str, filename: str, sheet_uuid: str, parent_path: str) -> str:
    return (
        "\t(sheet\n"
        "\t\t(at 50.8 50.8)\n"
        "\t\t(size 25.4 12.7)\n"
        "\t\t(fields_autoplaced yes)\n"
        "\t\t(stroke (width 0.1524) (type solid))\n"
        "\t\t(fill (color 0 0 0 0.0000))\n"
        f'\t\t(uuid "{sheet_uuid}")\n'
        f'\t\t(property "Sheetname" "{name}"\n'
        "\t\t\t(at 50.8 50.0 0)\n"
        "\t\t\t(effects (font (size 1.27 1.27)) (justify left bottom))\n"
        "\t\t)\n"
        f'\t\t(property "Sheetfile" "{filename}"\n'
        "\t\t\t(at 50.8 64.0 0)\n"
        "\t\t\t(effects (font (size 1.27 1.27)) (justify left top))\n"
        "\t\t)\n"
        "\t\t(instances\n"
        '\t\t\t(project "demo"\n'
        f'\t\t\t\t(path "{parent_path}" (page "2"))\n'
        "\t\t\t)\n"
        "\t\t)\n"
        "\t)\n"
    )


def _schematic(file_uuid: str, body: str = "", sheet_instances: str = "") -> str:
    return (
        "(kicad_sch\n"
        "\t(version 20250316)\n"
        '\t(generator "pytest")\n'
        f'\t(uuid "{file_uuid}")\n'
        '\t(paper "A4")\n'
        "\t(lib_symbols)\n"
        f"{body}"
        f"{sheet_instances}"
        "\t(embedded_fonts no)\n"
        ")\n"
    )


def _write_hierarchy(project: Path) -> tuple[Path, Path]:
    """Root -> Power (power.kicad_sch) -> Regulator (regulator.kicad_sch)."""
    root_sheet_instances = '\t(sheet_instances\n\t\t(path "/" (page "1"))\n\t)\n'
    (project / "demo.kicad_sch").write_text(
        _schematic(
            ROOT_UUID,
            _sheet_block("Power", "power.kicad_sch", POWER_SHEET_UUID, f"/{ROOT_UUID}"),
            root_sheet_instances,
        ),
        encoding="utf-8",
    )
    power = project / "power.kicad_sch"
    power.write_text(
        _schematic(
            POWER_FILE_UUID,
            _sheet_block(
                "Regulator",
                "regulator.kicad_sch",
                REGULATOR_SHEET_UUID,
                f"/{ROOT_UUID}/{POWER_SHEET_UUID}",
            ),
        ),
        encoding="utf-8",
    )
    regulator = project / "regulator.kicad_sch"
    regulator.write_text(_schematic(REGULATOR_FILE_UUID), encoding="utf-8")
    return power, regulator


def _symbol_paths(sheet: Path) -> set[str]:
    text = sheet.read_text(encoding="utf-8")
    symbol_blocks = [part.split("\n\t)", 1)[0] for part in text.split("\n\t(symbol\n")[1:]]
    return {path for block in symbol_blocks for path in _PATH.findall(block)}


async def _add_resistor(server: MCPServer, sheet_file: str, reference: str) -> str:
    return await call_tool_text(
        server,
        "sch_add_symbol",
        {
            "library": "Device",
            "symbol_name": "R",
            "x_mm": 100.0,
            "y_mm": 100.0,
            "reference": reference,
            "value": "10k",
            "sheet_file": sheet_file,
        },
    )


@pytest.mark.anyio
async def test_add_symbol_in_child_sheets_uses_hierarchical_path(
    sample_project: Path, mock_kicad: MagicMock
) -> None:
    power, regulator = _write_hierarchy(sample_project)
    server = build_server("schematic")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    await _add_resistor(server, "power.kicad_sch", "R1")
    await _add_resistor(server, "regulator.kicad_sch", "R2")
    await _add_resistor(server, "demo.kicad_sch", "R3")

    assert _symbol_paths(power) == {f"/{ROOT_UUID}/{POWER_SHEET_UUID}"}
    assert _symbol_paths(regulator) == {f"/{ROOT_UUID}/{POWER_SHEET_UUID}/{REGULATOR_SHEET_UUID}"}
    assert _symbol_paths(sample_project / "demo.kicad_sch") == {f"/{ROOT_UUID}"}


@pytest.mark.anyio
async def test_build_circuit_on_active_child_sheet_uses_hierarchical_path(
    sample_project: Path, mock_kicad: MagicMock
) -> None:
    power, _ = _write_hierarchy(sample_project)
    server = build_server("schematic")
    await call_tool_text(
        server,
        "kicad_set_project",
        {"project_dir": str(sample_project), "sch_file": str(power)},
    )

    await call_tool_text(
        server,
        "sch_build_circuit",
        {
            "symbols": [
                {
                    "library": "Device",
                    "symbol_name": "R",
                    "reference": "R1",
                    "value": "10k",
                    "x_mm": 50.8,
                    "y_mm": 60.96,
                }
            ],
            "power_symbols": [{"name": "GND", "x_mm": 76.2, "y_mm": 76.2}],
        },
    )

    paths = _symbol_paths(power)
    assert paths == {f"/{ROOT_UUID}/{POWER_SHEET_UUID}"}, paths

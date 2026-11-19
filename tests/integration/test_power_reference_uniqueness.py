"""Regression: power-symbol references must be unique across the whole project.

KiCad annotates ``#PWR``/``#FLG`` references project-wide, so the same reference
on two sheets is an annotation error. ``sch_build_circuit`` numbered power
symbols ``#PWR001...`` from 1 on every build, so every sheet built with it
repeated the same references, and ``PWR_FLAG`` symbols got ``#PWR`` instead of
KiCad's ``#FLG``. ``sch_add_power_symbol`` and the power terminals of
``sch_add_pin_labels`` derived the number from 16 bits of a fresh UUID, which
can repeat.
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from mcp.server.mcpserver import MCPServer

from kicad_mcp.server import build_server
from tests.conftest import call_tool_text

ROOT_UUID = "00000000-0000-0000-0000-000000000000"
# Digits required: the embedded lib_symbols definitions carry the bare "#PWR".
_REFERENCE = re.compile(r'\(property "Reference" "(#(?:PWR|FLG)\d+)"')


def _sheet_block(name: str, filename: str, sheet_uuid: str, y_mm: float) -> str:
    return (
        "\t(sheet\n"
        f"\t\t(at 50.8 {y_mm})\n"
        "\t\t(size 25.4 12.7)\n"
        f'\t\t(uuid "{sheet_uuid}")\n'
        f'\t\t(property "Sheetname" "{name}"\n'
        f"\t\t\t(at 50.8 {y_mm - 0.8} 0)\n"
        "\t\t\t(effects (font (size 1.27 1.27)) (justify left bottom))\n"
        "\t\t)\n"
        f'\t\t(property "Sheetfile" "{filename}"\n'
        f"\t\t\t(at 50.8 {y_mm + 13.5} 0)\n"
        "\t\t\t(effects (font (size 1.27 1.27)) (justify left top))\n"
        "\t\t)\n"
        "\t\t(instances\n"
        f'\t\t\t(project "demo" (path "/{ROOT_UUID}" (page "2")))\n'
        "\t\t)\n"
        "\t)\n"
    )


def _schematic(file_uuid: str, body: str = "") -> str:
    return (
        "(kicad_sch\n"
        "\t(version 20250316)\n"
        '\t(generator "pytest")\n'
        f'\t(uuid "{file_uuid}")\n'
        '\t(paper "A4")\n'
        "\t(lib_symbols)\n"
        f"{body}"
        '\t(sheet_instances\n\t\t(path "/" (page "1"))\n\t)\n'
        "\t(embedded_fonts no)\n"
        ")\n"
    )


def _write_two_sheet_project(project: Path) -> list[Path]:
    body = _sheet_block(
        "Power", "power.kicad_sch", "11111111-1111-4111-8111-111111111111", 50.8
    ) + _sheet_block("Logic", "logic.kicad_sch", "22222222-2222-4222-8222-222222222222", 76.2)
    (project / "demo.kicad_sch").write_text(_schematic(ROOT_UUID, body), encoding="utf-8")
    sheets = [project / "power.kicad_sch", project / "logic.kicad_sch"]
    for index, sheet in enumerate(sheets, start=3):
        sheet.write_text(
            _schematic(f"{index}{index}{index}{index}0000-0000-4000-8000-000000000000")
        )
    return sheets


def _power_references(project: Path) -> list[str]:
    references: list[str] = []
    for sheet in ("demo.kicad_sch", "power.kicad_sch", "logic.kicad_sch"):
        references += _REFERENCE.findall((project / sheet).read_text(encoding="utf-8"))
    return references


def _duplicates(references: list[str]) -> list[str]:
    return sorted(ref for ref, count in Counter(references).items() if count > 1)


async def _build_sheet(server: MCPServer, project: Path, sheet: Path) -> None:
    await call_tool_text(
        server, "kicad_set_project", {"project_dir": str(project), "sch_file": str(sheet)}
    )
    await call_tool_text(
        server,
        "sch_build_circuit",
        {
            "power_symbols": [
                {"name": "GND", "x_mm": 50.8, "y_mm": 76.2},
                {"name": "GND", "x_mm": 76.2, "y_mm": 76.2},
                {"name": "PWR_FLAG", "x_mm": 101.6, "y_mm": 76.2},
            ]
        },
    )


@pytest.mark.anyio
async def test_build_circuit_power_references_are_unique_across_sheets(
    sample_project: Path, mock_kicad: MagicMock
) -> None:
    power, logic = _write_two_sheet_project(sample_project)
    server = build_server("schematic")

    await _build_sheet(server, sample_project, power)
    await _build_sheet(server, sample_project, logic)
    # Rebuilding a sheet replaces its own symbols, so its old references are free again.
    await _build_sheet(server, sample_project, power)

    references = _power_references(sample_project)
    assert len(references) == 6
    assert _duplicates(references) == [], references
    flags = [ref for ref in references if ref.startswith("#FLG")]
    assert len(flags) == 2, references


@pytest.mark.anyio
async def test_added_power_symbols_never_repeat_a_project_reference(
    sample_project: Path, mock_kicad: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_two_sheet_project(sample_project)
    # A repeated UUID prefix is what made the old UUID-derived references collide.
    uuids = iter(f"abcd{index:04d}-0000-4000-8000-000000000000" for index in range(1000))
    monkeypatch.setattr("kicad_mcp.tools.schematic.new_uuid", lambda: next(uuids))
    server = build_server("schematic")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    for sheet_file, x_mm in (
        ("demo.kicad_sch", 25.4),
        ("power.kicad_sch", 25.4),
        ("power.kicad_sch", 50.8),
        ("logic.kicad_sch", 25.4),
    ):
        await call_tool_text(
            server,
            "sch_add_power_symbol",
            {"name": "GND", "x_mm": x_mm, "y_mm": 25.4, "sheet_file": sheet_file},
        )

    references = _power_references(sample_project)
    assert len(references) == 4
    assert _duplicates(references) == [], references

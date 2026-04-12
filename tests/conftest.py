"""Shared test fixtures for KiCad MCP Pro."""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


def tool_text(result: object) -> str:
    """Extract text from a FastMCP tool result."""
    if isinstance(result, tuple) and len(result) == 2:
        content, structured = result
        if isinstance(structured, dict) and "result" in structured:
            return str(structured["result"])
        return tool_text(content)
    if isinstance(result, dict):
        return json.dumps(result)
    if isinstance(result, Iterable) and not isinstance(result, (str, bytes, dict)):
        parts = []
        for item in result:
            if hasattr(item, "text"):
                parts.append(item.text)
            else:
                parts.append(str(item))
        return "\n".join(parts)
    return str(result)


async def call_tool_text(server: object, name: str, arguments: dict[str, object]) -> str:
    """Call a FastMCP tool and normalize its textual output."""
    result = await server.call_tool(name, arguments)
    return tool_text(result)


async def read_resource_text(server: object, uri: str) -> str:
    """Read an MCP resource and normalize its textual output."""
    result = await server.read_resource(uri)
    return tool_text(list(result))


async def get_prompt_text(server: object, name: str, arguments: dict[str, object]) -> str:
    """Read an MCP prompt and normalize the returned text content."""
    result = await server.get_prompt(name, arguments)
    return tool_text([result.messages[0].content])


@pytest.fixture(autouse=True)
def reset_globals(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reset cached config and KiCad connection state before every test."""
    from kicad_mcp.config import reset_config
    from kicad_mcp.connection import reset_connection

    reset_config()
    reset_connection()
    monkeypatch.delenv("KICAD_MCP_PROJECT_DIR", raising=False)
    monkeypatch.delenv("KICAD_MCP_PROJECT_FILE", raising=False)
    monkeypatch.delenv("KICAD_MCP_PCB_FILE", raising=False)
    monkeypatch.delenv("KICAD_MCP_SCH_FILE", raising=False)
    monkeypatch.delenv("KICAD_MCP_OUTPUT_DIR", raising=False)
    monkeypatch.delenv("KICAD_MCP_SYMBOL_LIBRARY_DIR", raising=False)
    monkeypatch.delenv("KICAD_MCP_FOOTPRINT_LIBRARY_DIR", raising=False)
    monkeypatch.delenv("KICAD_MCP_KICAD_CLI", raising=False)
    monkeypatch.delenv("KICAD_MCP_TRANSPORT", raising=False)
    monkeypatch.delenv("KICAD_MCP_PROFILE", raising=False)
    monkeypatch.delenv("KICAD_MCP_ENABLE_EXPERIMENTAL_TOOLS", raising=False)


@pytest.fixture
def fake_cli(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Create a fake kicad-cli executable path."""
    cli = tmp_path / "kicad-cli"
    cli.write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setenv("KICAD_MCP_KICAD_CLI", str(cli))
    return cli


@pytest.fixture
def sample_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_cli: Path) -> Path:
    """Create a minimal KiCad project and library layout."""
    project_dir = tmp_path / "project"
    project_dir.mkdir()

    (project_dir / "demo.kicad_pro").write_text('{"meta": {"version": 1}}', encoding="utf-8")
    (project_dir / "demo.kicad_pcb").write_text("(kicad_pcb)\n", encoding="utf-8")
    (project_dir / "demo.kicad_dru").write_text("(rules)\n", encoding="utf-8")
    (project_dir / "demo.kicad_sch").write_text(
        (
            "(kicad_sch\n"
            "\t(version 20250316)\n"
            '\t(generator "pytest")\n'
            '\t(uuid "00000000-0000-0000-0000-000000000000")\n'
            '\t(paper "A4")\n'
            "\t(lib_symbols)\n"
            "\t(sheet_instances\n"
            '\t\t(path "/" (page "1"))\n'
            "\t)\n"
            "\t(embedded_fonts no)\n"
            ")\n"
        ),
        encoding="utf-8",
    )

    symbols_dir = tmp_path / "symbols"
    symbols_dir.mkdir()
    (symbols_dir / "Device.kicad_sym").write_text(
        (
            "(kicad_symbol_lib (version 20250316) (generator pytest)\n"
            '  (symbol "R"\n'
            '    (property "Reference" "R" (id 0) (at 0 2.54 0))\n'
            '    (property "Value" "R" (id 1) (at 0 -2.54 0))\n'
            '    (property "Description" "Resistor")\n'
            '    (property "ki_keywords" "resistor ohm")\n'
            '    (property "Footprint" "Resistor_SMD:R_0805")\n'
            '    (property "Datasheet" "https://example.com/r.pdf")\n'
            '    (pin passive line (at -2.54 0 0) (length 2.54) (name "1") (number "1"))\n'
            '    (pin passive line (at 2.54 0 180) (length 2.54) (name "2") (number "2"))\n'
            "  )\n"
            ")\n"
        ),
        encoding="utf-8",
    )
    (symbols_dir / "power.kicad_sym").write_text(
        (
            "(kicad_symbol_lib (version 20250316) (generator pytest)\n"
            '  (symbol "GND"\n'
            "    (power global)\n"
            '    (property "Reference" "#PWR" (id 0) (at 0 2.54 0))\n'
            '    (property "Value" "GND" (id 1) (at 0 -2.54 0))\n'
            '    (symbol "GND_0_1"\n'
            "      (polyline (pts (xy 0 0) (xy 0 -1.27)))\n"
            "    )\n"
            '    (symbol "GND_1_1"\n'
            '      (pin power_in line (at 0 0 270) (length 0) (name "") (number "1"))\n'
            "    )\n"
            "  )\n"
            ")\n"
        ),
        encoding="utf-8",
    )

    footprints_dir = tmp_path / "footprints"
    footprints_dir.mkdir()
    resistor_lib = footprints_dir / "Resistor_SMD.pretty"
    resistor_lib.mkdir()
    (resistor_lib / "R_0805.kicad_mod").write_text(
        '(module R_0805 (model "Resistor_SMD.3dshapes/R_0805.wrl"))\n',
        encoding="utf-8",
    )
    (resistor_lib / "R_1206.kicad_mod").write_text(
        '(module R_1206 (model "Resistor_SMD.3dshapes/R_1206.wrl"))\n',
        encoding="utf-8",
    )

    monkeypatch.setenv("KICAD_MCP_PROJECT_DIR", str(project_dir))
    monkeypatch.setenv("KICAD_MCP_SYMBOL_LIBRARY_DIR", str(symbols_dir))
    monkeypatch.setenv("KICAD_MCP_FOOTPRINT_LIBRARY_DIR", str(footprints_dir))
    return project_dir


@pytest.fixture
def mock_kicad() -> MagicMock:
    """Mock KiCad IPC connection."""
    with patch("kicad_mcp.connection.KiCad") as mocked:
        instance = MagicMock()
        instance.get_version.return_value = "10.0.1"
        instance.get_open_documents.return_value = []
        mocked.return_value = instance
        yield instance


@pytest.fixture
def mock_board(mock_kicad: MagicMock) -> MagicMock:
    """Mock the active board object."""
    board = MagicMock()
    board.get_tracks.return_value = []
    board.get_vias.return_value = []
    board.get_footprints.return_value = []
    board.get_nets.return_value = []
    board.get_zones.return_value = []
    board.get_shapes.return_value = []
    board.get_pads.return_value = []
    board.get_enabled_layers.return_value = []
    board.get_selection.return_value = []
    board.get_stackup.return_value.layers = []
    board.get_as_string.return_value = "(kicad_pcb)"
    mock_kicad.get_board.return_value = board
    return board

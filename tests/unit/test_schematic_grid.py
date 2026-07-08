from __future__ import annotations

import importlib

import pytest

import kicad_mcp.tools.schematic_constants as schematic_constants
from kicad_mcp.tools import schematic


def test_schematic_default_grid_is_50_mil() -> None:
    assert schematic_constants.DEFAULT_SCHEMATIC_GRID_MM == pytest.approx(1.27)
    assert schematic_constants.SCHEMATIC_GRID_MM == pytest.approx(1.27)
    assert schematic._snap_schematic_coord(2.0) == pytest.approx(2.54)
    assert schematic._snap_schematic_coord(3.2) == pytest.approx(3.81)


def test_schematic_grid_override(monkeypatch) -> None:
    monkeypatch.setenv("KICAD_MCP_SCHEMATIC_GRID_MM", "0.635")
    reloaded = importlib.reload(schematic_constants)
    try:
        assert reloaded.SCHEMATIC_GRID_MM == pytest.approx(0.635)
    finally:
        monkeypatch.delenv("KICAD_MCP_SCHEMATIC_GRID_MM", raising=False)
        importlib.reload(schematic_constants)


def test_schematic_grid_invalid_values_fall_back(monkeypatch) -> None:
    for value in ["", "nope", "-1", "0", "100"]:
        monkeypatch.setenv("KICAD_MCP_SCHEMATIC_GRID_MM", value)
        reloaded = importlib.reload(schematic_constants)
        assert reloaded.SCHEMATIC_GRID_MM == pytest.approx(1.27)
    monkeypatch.delenv("KICAD_MCP_SCHEMATIC_GRID_MM", raising=False)
    importlib.reload(schematic_constants)

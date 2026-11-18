"""Regression: file-based PCB writers must refuse while the board is open in KiCad.

These tools rewrite ``.kicad_pcb`` on disk behind KiCad's back. Without the
open-board guard that ``pcb_sync_from_schematic`` and friends already use, an
open session either overwrites the change on its next save or, for
``pcb_set_stackup``, is reloaded and loses its unsaved edits.

Each case sets up valid inputs with the board closed first, so that without
the guard the tool really writes the board file (the test then fails on the
changed bytes, not on an input error).
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from mcp.server.mcpserver import MCPServer
from PIL import Image

from kicad_mcp.server import build_server
from tests.conftest import call_tool_text

_FOOTPRINT_R1 = (
    '(footprint "Resistor_SMD:R_0603_1608Metric"\n'
    '\t(layer "F.Cu")\n'
    '\t(uuid "11111111-1111-1111-1111-111111111111")\n'
    "\t(at 20 20 0)\n"
    '\t(property "Reference" "R1"\n\t\t(at 0 -1.5 0)\n\t\t(layer "F.SilkS")\n\t)\n'
    '\t(property "Value" "10k"\n\t\t(at 0 1.5 0)\n\t\t(layer "F.Fab")\n\t)\n'
    ")"
)

_TWO_LAYER = [
    {"name": "F_Cu", "type": "signal", "thickness_mm": 0.035, "material": "Copper"},
    {"name": "dielectric_1", "type": "core", "thickness_mm": 1.51, "material": "FR4"},
    {"name": "B_Cu", "type": "signal", "thickness_mm": 0.035, "material": "Copper"},
]

_FOUR_LAYER = [
    {"name": "F_Cu", "type": "signal", "thickness_mm": 0.035, "material": "Copper"},
    {"name": "dielectric_1", "type": "prepreg", "thickness_mm": 0.2, "material": "FR4"},
    {"name": "In1_Cu", "type": "ground", "thickness_mm": 0.018, "material": "Copper"},
    {"name": "dielectric_2", "type": "core", "thickness_mm": 1.0, "material": "FR4"},
    {"name": "In2_Cu", "type": "power", "thickness_mm": 0.018, "material": "Copper"},
    {"name": "dielectric_3", "type": "prepreg", "thickness_mm": 0.2, "material": "FR4"},
    {"name": "B_Cu", "type": "signal", "thickness_mm": 0.035, "material": "Copper"},
]

Setup = Callable[[MCPServer, Path], Awaitable[dict[str, Any]]]


async def _barcode(_server: MCPServer, _project: Path) -> dict[str, Any]:
    return {"content": "SN-0001", "x_mm": 10.0, "y_mm": 10.0}


async def _bitmap(_server: MCPServer, project: Path) -> dict[str, Any]:
    image = project / "logo.png"
    Image.new("L", (4, 4), 0).save(image)
    return {"source_image": str(image), "x_mm": 10.0, "y_mm": 10.0, "width_mm": 4.0}


async def _inner_layer(server: MCPServer, project: Path) -> dict[str, Any]:
    await call_tool_text(server, "pcb_set_stackup", {"layers": _FOUR_LAYER})
    board = project / "demo.kicad_pcb"
    text = board.read_text(encoding="utf-8").rstrip()
    assert text.endswith(")")
    board.write_text(f"{text[:-1]}\t{_FOOTPRINT_R1}\n)\n", encoding="utf-8")
    return {"reference": "R1", "layer": "In1.Cu", "shape_type": "rect"}


async def _block_place(_server: MCPServer, project: Path) -> dict[str, Any]:
    state = project / ".kicad-mcp" / "pcb_blocks.json"
    state.parent.mkdir(parents=True, exist_ok=True)
    block = {"reference": "R1", "dx_mm": 0.0, "dy_mm": 0.0, "rotation": 0, "block": _FOOTPRINT_R1}
    state.write_text(json.dumps({"blocks": {"power": {"footprints": [block]}}}), encoding="utf-8")
    return {"block_name": "power", "x_mm": 30.0, "y_mm": 30.0}


async def _stackup(_server: MCPServer, _project: Path) -> dict[str, Any]:
    return {"layers": _TWO_LAYER}


def _recorder(reloads: list[str]) -> Callable[[], str]:
    def reload() -> str:
        reloads.append("reload")
        return "reloaded"

    return reload


_CASES: list[tuple[str, Setup]] = [
    ("pcb_add_barcode", _barcode),
    ("pcb_add_bitmap_board_art", _bitmap),
    ("add_footprint_inner_layer_graphic", _inner_layer),
    ("pcb_block_place", _block_place),
    ("pcb_set_stackup", _stackup),
]


@pytest.mark.anyio
@pytest.mark.parametrize(("tool", "setup"), _CASES, ids=[name for name, _ in _CASES])
async def test_file_based_pcb_writer_refuses_while_board_is_open(
    sample_project: Path,
    mock_board: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
    tool: str,
    setup: Setup,
) -> None:
    board_open = False
    reloads: list[str] = []
    monkeypatch.setattr("kicad_mcp.tools.pcb._board_is_open", lambda: board_open)
    monkeypatch.setattr("kicad_mcp.tools.pcb._reload_board_after_file_sync", _recorder(reloads))
    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})
    arguments = await setup(server, sample_project)
    reloads.clear()

    board = sample_project / "demo.kicad_pcb"
    before = board.read_bytes()
    board_open = True

    result = await call_tool_text(server, tool, arguments)

    assert "Refusing file-based" in result, result
    assert "allow_open_board=True" in result
    assert board.read_bytes() == before
    assert reloads == []


@pytest.mark.anyio
async def test_file_based_pcb_writer_proceeds_and_reloads_when_allowed(
    sample_project: Path,
    mock_board: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reloads: list[str] = []
    monkeypatch.setattr("kicad_mcp.tools.pcb._board_is_open", lambda: True)
    monkeypatch.setattr("kicad_mcp.tools.pcb._reload_board_after_file_sync", _recorder(reloads))
    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    result = await call_tool_text(
        server,
        "pcb_add_barcode",
        {"content": "SN-0001", "x_mm": 10.0, "y_mm": 10.0, "allow_open_board": True},
    )

    assert "Barcode added" in result
    assert "(barcode" in (sample_project / "demo.kicad_pcb").read_text(encoding="utf-8")
    assert reloads == ["reload"]


@pytest.mark.anyio
async def test_stackup_explicit_open_board_opt_in_reloads_once(
    sample_project: Path,
    mock_board: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reloads: list[str] = []
    monkeypatch.setattr("kicad_mcp.tools.pcb._board_is_open", lambda: True)
    monkeypatch.setattr("kicad_mcp.tools.pcb._reload_board_after_file_sync", _recorder(reloads))
    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    result = await call_tool_text(
        server, "pcb_set_stackup", {"layers": _TWO_LAYER, "allow_open_board": True}
    )

    assert "Configured stackup" in result
    assert reloads == ["reload"]
    assert (sample_project / "output" / "stackup_profile.json").exists()

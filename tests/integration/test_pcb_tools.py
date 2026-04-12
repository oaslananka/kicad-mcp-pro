from __future__ import annotations

import pytest

from kicad_mcp.server import build_server
from tests.conftest import call_tool_text


@pytest.mark.anyio
async def test_pcb_summary_tool(mock_board) -> None:
    server = build_server("pcb")
    text = await call_tool_text(server, "pcb_get_board_summary", {})
    assert "Board summary" in text


@pytest.mark.anyio
async def test_pcb_add_track_creates_item(mock_board) -> None:
    server = build_server("pcb")
    await server.call_tool(
        "pcb_add_track",
        {
            "x1_mm": 0.0,
            "y1_mm": 0.0,
            "x2_mm": 10.0,
            "y2_mm": 0.0,
            "layer": "F_Cu",
            "width_mm": 0.25,
            "net_name": "NET1",
        },
    )
    assert mock_board.create_items.called

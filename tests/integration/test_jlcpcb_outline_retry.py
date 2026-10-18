"""#1314: a repeated outline operation must not multiply Edge.Cuts geometry."""

from __future__ import annotations

import pytest
from kipy.board_types import BoardCircle
from kipy.proto.board.board_types_pb2 import BoardLayer

from kicad_mcp.server import build_server
from tests.conftest import call_tool_text


@pytest.mark.anyio
async def test_set_board_outline_retry_is_idempotent_and_refuses_conflicts(mock_board) -> None:
    edge_shapes = []
    mock_board.get_shapes.side_effect = lambda: list(edge_shapes)

    def create(items):
        edge_shapes.extend(items)
        return items

    mock_board.create_items.side_effect = create
    server = build_server("pcb")
    dimensions = {
        "width_mm": 63.0,
        "height_mm": 33.0,
        "origin_x_mm": 0.0,
        "origin_y_mm": 0.0,
    }

    first = await call_tool_text(server, "pcb_set_board_outline", dimensions)
    assert "added successfully" in first
    assert len(edge_shapes) == 1

    retry = await call_tool_text(server, "pcb_set_board_outline", dimensions)
    assert "already matches" in retry
    assert len(edge_shapes) == 1
    assert mock_board.create_items.call_count == 1

    conflict = await call_tool_text(
        server, "pcb_set_board_outline", {**dimensions, "width_mm": 62.0}
    )
    assert "existing Edge.Cuts" in conflict
    assert len(edge_shapes) == 1
    assert mock_board.create_items.call_count == 1


@pytest.mark.anyio
async def test_set_board_outline_refuses_custom_existing_edge_geometry(mock_board) -> None:
    custom = BoardCircle()
    custom.layer = BoardLayer.BL_Edge_Cuts
    mock_board.get_shapes.return_value = [custom]

    result = await call_tool_text(
        build_server("pcb"), "pcb_set_board_outline", {"width_mm": 63, "height_mm": 33}
    )
    assert "existing Edge.Cuts" in result
    mock_board.create_items.assert_not_called()

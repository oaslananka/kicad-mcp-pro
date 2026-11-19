"""Regression: pcb_set_board_outline must be able to round the board's corners.

The tool only took width and height, so a board with rounded corners needed a
hand-drawn outline of four lines and four arcs. KiCad 10's API rectangle carries
a ``corner_radius``; the tool now sets it, keeps the retry check exact (same
corners *and* radius), and rejects a radius larger than half the shorter side.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
from kipy.board_types import BoardRectangle

from kicad_mcp.server import build_server
from tests.conftest import call_tool_text

DIMENSIONS = {"width_mm": 86.0, "height_mm": 55.0, "origin_x_mm": 10.0, "origin_y_mm": 20.0}


def _board_with_edge_list(mock_board: MagicMock) -> list[Any]:
    edge_shapes: list[Any] = []
    mock_board.get_shapes.side_effect = lambda: list(edge_shapes)

    def create(items: list[Any]) -> list[Any]:
        edge_shapes.extend(items)
        return items

    mock_board.create_items.side_effect = create
    return edge_shapes


def _corner_radius_nm(shape: BoardRectangle) -> int:
    return int(shape.proto.shape.rectangle.corner_radius.value_nm)


@pytest.mark.anyio
async def test_outline_sets_corner_radius_and_retry_compares_it(mock_board: MagicMock) -> None:
    edges = _board_with_edge_list(mock_board)
    server = build_server("pcb")

    first = await call_tool_text(
        server, "pcb_set_board_outline", {**DIMENSIONS, "corner_radius_mm": 2.0}
    )

    assert "added successfully" in first, first
    assert len(edges) == 1
    assert isinstance(edges[0], BoardRectangle)
    assert _corner_radius_nm(edges[0]) == 2_000_000

    retry = await call_tool_text(
        server, "pcb_set_board_outline", {**DIMENSIONS, "corner_radius_mm": 2.0}
    )
    assert "already matches" in retry
    other_radius = await call_tool_text(
        server, "pcb_set_board_outline", {**DIMENSIONS, "corner_radius_mm": 3.0}
    )
    assert "existing Edge.Cuts" in other_radius
    assert mock_board.create_items.call_count == 1


@pytest.mark.anyio
async def test_outline_without_radius_stays_a_sharp_rectangle(mock_board: MagicMock) -> None:
    edges = _board_with_edge_list(mock_board)

    result = await call_tool_text(build_server("pcb"), "pcb_set_board_outline", DIMENSIONS)

    assert "added successfully" in result
    assert _corner_radius_nm(edges[0]) == 0


@pytest.mark.anyio
async def test_outline_rejects_a_radius_larger_than_half_the_short_side(
    mock_board: MagicMock,
) -> None:
    _board_with_edge_list(mock_board)

    result = await call_tool_text(
        build_server("pcb"), "pcb_set_board_outline", {**DIMENSIONS, "corner_radius_mm": 28.0}
    )

    assert "corner_radius_mm" in result, result
    mock_board.create_items.assert_not_called()

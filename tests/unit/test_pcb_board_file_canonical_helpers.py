"""Protect the single canonical pure board-file parser/geometry implementation."""

from __future__ import annotations

from kicad_mcp.tools import board_file, pcb

_CANONICAL_HELPERS = (
    "_bbox_from_block",
    "_board_frame_mm",
    "_default_board_text",
    "_edge_cuts_bounds",
    "_iter_blocks",
    "_normalize_board_content",
    "_parse_board_footprint_blocks",
    "_placement_boxes_overlap",
)


def test_pcb_reuses_board_file_helpers_by_identity() -> None:
    for name in _CANONICAL_HELPERS:
        assert getattr(pcb, name) is getattr(board_file, name), name

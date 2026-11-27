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


def test_outline_ignores_other_layers_and_quoted_phantom_geometry() -> None:
    from kicad_mcp.tools import dfm

    content = r"""(kicad_pcb
        (gr_rect (start -100 -100) (end 100 100) (layer "F.SilkS"))
        (gr_text "(gr_line (start -200 -200) (end 200 200) (layer \"Edge.Cuts\"))")
        (gr_rect (start 1 2) (end 11 22) (layer "Edge.Cuts")))"""
    assert board_file._edge_cuts_bounds(content) == (1, 2, 11, 22)
    assert dfm._outline_bounds_mm(content) == (1, 2, 11, 22)

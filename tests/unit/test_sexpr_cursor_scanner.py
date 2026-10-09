"""S-expression cursor scans must not copy every progressively shorter suffix."""

from __future__ import annotations

from kicad_mcp.tools import board_file, pcb, schematic


class NoSuffixCopy(str):
    def __getitem__(self, key: int | slice) -> str:
        if isinstance(key, slice) and key.start is not None and key.stop is None:
            raise AssertionError("scanning must not copy the remaining text")
        return super().__getitem__(key)


def test_board_and_schematic_scanners_do_not_copy_input_suffixes() -> None:
    text = NoSuffixCopy("x" * 60000)
    assert list(board_file._iter_blocks(text, "pad")) == []
    assert list(pcb._iter_blocks(text, "footprint")) == []
    assert schematic._find_placed_symbol_blocks(text, "R1") == []


def test_cursor_parser_still_finds_valid_blocks() -> None:
    content = '(pad "1" smd rect (at 0 0) (size 1 1))\n'
    assert list(board_file._iter_blocks(content, "pad")) == [content.strip()]

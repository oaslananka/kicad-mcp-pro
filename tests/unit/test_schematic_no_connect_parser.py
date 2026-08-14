from __future__ import annotations

from kicad_mcp.tools.schematic import _parse_no_connect_block


def test_parse_no_connect_block_returns_none_for_malformed_block() -> None:
    block = '(no_connect (uuid "missing-at"))'

    assert _parse_no_connect_block(block) is None

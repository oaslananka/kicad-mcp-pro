"""String-level S-expression escape/unescape round trip (work order P2-T2, K6).

This is a *string escaping* round trip, not a file round trip. It was previously named
``test_sexpr_property.py::test_sexpr_roundtrip``, which misleadingly implied it proved
schematic-file fidelity. Real file round-trip fidelity is covered by
``tests/integration/test_roundtrip_fidelity.py``.
"""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from kicad_mcp.utils.sexpr import _sexpr_string, _unescape_sexpr_string


@given(st.text(min_size=0, max_size=200))
def test_sexpr_string_escape_roundtrip(s: str) -> None:
    encoded = _sexpr_string(s)
    decoded = _unescape_sexpr_string(encoded[1:-1])

    assert decoded == s.replace("\r\n", "\n").replace("\r", "\n")


def test_update_property_replaces_entire_escaped_value() -> None:
    from kicad_mcp.tools.schematic import _update_symbol_property_block

    field = 'Vendor "name"'
    old = 'old "quoted" \\ path'
    new = 'new "quoted" \\ path'
    property_text = f"(property {_sexpr_string(field)} {_sexpr_string(old)} (at 1 2 0))"
    block = f'(symbol {property_text} (property "Value" "unchanged"))'
    expected = block.replace(_sexpr_string(old), _sexpr_string(new))
    assert _update_symbol_property_block(block, {}, field, new) == expected


def test_update_existing_escaped_value_keeps_other_properties() -> None:
    from kicad_mcp.tools.schematic import _update_symbol_property_block

    old = _sexpr_string('old "quoted" \\ path')
    block = f'(symbol (property "Value" {old} (at 1 2 0)) (property "Other" "unchanged"))'
    assert _update_symbol_property_block(block, {}, "Value", "new") == block.replace(old, '"new"')


def test_generated_board_markers_escape_reference_literals() -> None:
    from kicad_mcp.tools.pcb import _fiducial_block, _mounting_hole_block
    from kicad_mcp.utils.sexpr import _extract_block

    reference = 'H1" \\ (other)'
    for block in (_fiducial_block(reference, 1, 2, 1), _mounting_hole_block(reference, 1, 2, 3, 1)):
        assert f'(property "Reference" {_sexpr_string(reference)}' in block
        assert _extract_block(block, 0) == (block, len(block))

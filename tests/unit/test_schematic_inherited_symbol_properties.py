"""Flattening KiCad inherited library symbols must retain all derived properties."""

from kicad_mcp.tools.schematic import _flatten_extends_symbol, _symbol_property_blocks


def test_flatten_inherited_symbol_retains_new_properties_from_every_level() -> None:
    base = """(symbol "Base"
        (property "Reference" "U" (at 0 0 0))
        (property "Value" "Base" (at 0 2.54 0))
        (symbol "Base_0_1" (rectangle (start -2.54 2.54) (end 2.54 -2.54)))
    )"""
    intermediate = """(symbol "Middle"
        (extends "Base")
        (property "Reference" "TP" (at 0 0 0))
        (property "Value" "Middle" (at 0 2.54 0))
        (property "Manufacturer" "Example Corp" (at 0 0 0))
    )"""
    derived = """(symbol "Child"
        (extends "Middle")
        (property "Value" "Child" (at 0 2.54 0))
        (property "Part Number" "CHILD-8" (at 0 0 0))
    )"""

    result = _flatten_extends_symbol("Test", "Child", [base, intermediate, derived])

    assert '(symbol "Test:Child"' in result
    assert '(symbol "Child_0_1"' in result
    assert "(extends " not in result
    props = _symbol_property_blocks(result)
    assert '"TP"' in props["Reference"]
    assert '"Child"' in props["Value"]
    assert '"Example Corp"' in props["Manufacturer"]
    assert '"CHILD-8"' in props["Part Number"]
    assert len(props) == 4


def test_empty_derived_footprint_inherits_base_default() -> None:
    base = """(symbol "Base"
        (property "Reference" "U" (at 0 0 0))
        (property "Value" "Base" (at 0 2.54 0))
        (property "Footprint" "Package_SO:SOIC-8" (at 0 0 0))
        (symbol "Base_0_1" (rectangle (start -2.54 2.54) (end 2.54 -2.54)))
    )"""
    derived = """(symbol "Child"
        (extends "Base")
        (property "Value" "Child" (at 0 2.54 0))
        (property "Footprint" "" (at 0 0 0))
    )"""
    flat = _flatten_extends_symbol("Example", "Child", [base, derived])
    assert '"Package_SO:SOIC-8"' in _symbol_property_blocks(flat)["Footprint"]


def test_empty_intermediate_footprint_does_not_hide_base_default() -> None:
    base = """(symbol "Base"
        (property "Footprint" "Package_SO:SOIC-8" (at 0 0 0))
        (symbol "Base_0_1" (rectangle (start -2.54 2.54) (end 2.54 -2.54)))
    )"""
    middle = """(symbol "Middle"
        (extends "Base")
        (property "Footprint" "" (at 0 0 0))
    )"""
    leaf = """(symbol "Child"
        (extends "Middle")
        (property "Value" "Child" (at 0 2.54 0))
    )"""
    flat = _flatten_extends_symbol("Example", "Child", [base, middle, leaf])
    assert '"Package_SO:SOIC-8"' in _symbol_property_blocks(flat)["Footprint"]

    overriding_leaf = """(symbol "Child"
        (extends "Middle")
        (property "Footprint" "Package_DIP:DIP-8" (at 0 0 0))
    )"""
    overridden = _flatten_extends_symbol("Example", "Child", [base, middle, overriding_leaf])
    assert '"Package_DIP:DIP-8"' in _symbol_property_blocks(overridden)["Footprint"]

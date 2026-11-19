"""Reference synchronization must avoid foreign project instances and cascading edits."""

from kicad_mcp.schematic.instance_paths import (
    rewrite_placed_symbol_references,
    rewrite_symbol_instance_reference,
)


def test_reference_change_preserves_foreign_projects() -> None:
    symbol = (
        '(symbol (lib_id "Device:R") (property "Reference" "R5") '
        '(instances (project "demo" (path "/root" (reference "R5") (unit 1))) '
        '(project "other" (path "/root" (reference "R5") (unit 1)))))'
    )
    updated = rewrite_symbol_instance_reference(symbol, "R5", "R14", "demo")
    assert '(project "demo" (path "/root" (reference "R14")' in updated
    assert '(project "other" (path "/root" (reference "R5")' in updated


def test_two_symbol_renames_do_not_cascade() -> None:
    content = (
        "(kicad_sch "
        '(symbol (lib_id "Device:R") (property "Reference" "R1") '
        '(instances (project "demo" (path "/root" (reference "R1"))))) '
        '(symbol (lib_id "Device:R") (property "Reference" "R2") '
        '(instances (project "demo" (path "/root" (reference "R2"))))))'
    )
    updated = rewrite_placed_symbol_references(content, [("R1", "R2"), ("R2", "R3")], "demo")
    assert updated.count('(property "Reference" "R2")') == 1
    assert updated.count('(property "Reference" "R3")') == 1
    assert updated.count('(reference "R2")') == 1
    assert updated.count('(reference "R3")') == 1
    assert '(reference "R1")' not in updated

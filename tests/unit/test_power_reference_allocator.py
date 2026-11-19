from __future__ import annotations

from pathlib import Path

from kicad_mcp.schematic.references import (
    PowerReferenceAllocator,
    hierarchy_files,
    project_references,
)


def test_allocator_skips_used_numbers_and_numbers_flags_separately() -> None:
    allocator = PowerReferenceAllocator({"#PWR001", "#PWR003", "#FLG001"})

    assert [allocator.allocate(name) for name in ("GND", "+5V", "GND")] == [
        "#PWR002",
        "#PWR004",
        "#PWR005",
    ]
    assert allocator.allocate("PWR_FLAG") == "#FLG002"


def _sheet(sheet_file: str) -> str:
    return f'\t(sheet\n\t\t(property "Sheetfile" "{sheet_file}")\n\t)\n'


def _symbol(reference: str) -> str:
    return (
        f'\t(symbol\n\t\t(property "Reference" "{reference}")\n'
        f'\t\t(instances (project "demo" (path "/x" (reference "{reference}") (unit 1))))\n\t)\n'
    )


def test_project_references_walk_the_hierarchy_and_can_leave_out_the_target(
    tmp_path: Path,
) -> None:
    root = tmp_path / "demo.kicad_sch"
    child = tmp_path / "child.kicad_sch"
    stray = tmp_path / "stray.kicad_sch"
    root.write_text(f"(kicad_sch\n{_sheet('child.kicad_sch')}{_symbol('#PWR001')})\n")
    child.write_text(f"(kicad_sch\n{_sheet('demo.kicad_sch')}{_symbol('#PWR002')})\n")
    stray.write_text(f"(kicad_sch\n{_symbol('#PWR003')})\n")

    assert hierarchy_files(root) == [root.resolve(), child.resolve()]
    assert project_references(root, child, include_target=False) == {"#PWR001"}
    assert project_references(root, stray, include_target=True) == {
        "#PWR001",
        "#PWR002",
        "#PWR003",
    }

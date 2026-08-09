from __future__ import annotations

from pathlib import Path

from kicad_mcp.schematic.topology import SchematicTopologyService

SHEET = """(kicad_sch
\t(sheet
\t\t(at 80.01 30.48)
\t\t(size 30.48 20.32)
\t\t(property "Sheetname" "02_mcu"
\t\t\t(at 80.01 29.77 0)
\t\t)
\t\t(property "Sheetfile" "child.kicad_sch"
\t\t\t(at 80.01 51.38 0)
\t\t)
\t\t(pin "VIN" input
\t\t\t(at 80.01 33.02 180)
\t\t\t(uuid "u-1")
\t\t)
\t\t(instances
\t\t\t(project "main" (path "/1" (page "2")))
\t\t)
\t)
)
"""


def _service(text: str) -> SchematicTopologyService:
    return SchematicTopologyService(
        load_schematic=lambda path: (_ for _ in ()).throw(AssertionError("must not load")),
        with_diagnostics=lambda result, path: result,
        build_connectivity_groups=lambda path: [],
        iter_child_sheet_paths=lambda path: [],
        parse_schematic=lambda path: {},
        warn=lambda event, **fields: None,
        read_text=lambda path: text,
    )


def test_list_sheet_pins_reports_name_type_and_position(tmp_path: Path) -> None:
    report = _service(SHEET).list_sheet_pins(tmp_path / "root.kicad_sch", "02_mcu")

    assert "VIN" in report
    assert "input" in report
    # The pin's own position (80.01, 33.02) and its rotation-derived edge
    # ("left" for rotation 180) -- distinct from the sheet symbol's origin
    # (80.01, 30.48), so this fails if per-pin geometry goes missing even
    # though the sheet-level summary line still mentions "80.01".
    assert "VIN (input, left) @ (80.01, 33.02) mm" in report


def test_list_sheet_pins_reports_an_empty_sheet(tmp_path: Path) -> None:
    text = SHEET.replace(
        '\t\t(pin "VIN" input\n\t\t\t(at 80.01 33.02 180)\n\t\t\t(uuid "u-1")\n\t\t)\n', ""
    )

    report = _service(text).list_sheet_pins(tmp_path / "root.kicad_sch", "02_mcu")

    assert "no sheet pins" in report.casefold()


def test_list_sheet_pins_reports_a_missing_sheet(tmp_path: Path) -> None:
    report = _service(SHEET).list_sheet_pins(tmp_path / "root.kicad_sch", "nope")

    assert "not found" in report.casefold()


def test_list_sheet_pins_reports_read_failures_and_warns(tmp_path: Path) -> None:
    warnings: list[tuple[str, dict[str, object]]] = []

    def _raising_read_text(_path: Path) -> str:
        raise OSError("disk exploded")

    service = SchematicTopologyService(
        load_schematic=lambda path: (_ for _ in ()).throw(AssertionError("must not load")),
        with_diagnostics=lambda result, path: result,
        build_connectivity_groups=lambda path: [],
        iter_child_sheet_paths=lambda path: [],
        parse_schematic=lambda path: {},
        warn=lambda event, **fields: warnings.append((event, fields)),
        read_text=_raising_read_text,
    )
    schematic_file = tmp_path / "root.kicad_sch"

    report = service.list_sheet_pins(schematic_file, "02_mcu")

    assert report == f"Could not read '{schematic_file.name}': disk exploded"
    assert warnings == [
        (
            "schematic_list_sheet_pins_failed",
            {
                "schematic_file": str(schematic_file),
                "sheet_name": "02_mcu",
                "error": "disk exploded",
            },
        )
    ]

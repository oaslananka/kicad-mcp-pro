"""End-to-end coverage: hierarchical sheet pins on a real project.

The unit tests around ``kicad_mcp.schematic.sheet_pins`` prove our emitted
``(pin ...)`` text is what *we* intended. This module proves it is what
*KiCad's own data model* expects, by writing pins through the real
``sch_import_sheet_pins`` tool -- the same text-splice code path the server
uses in production -- and reading the result back through ``kicad_sch_api``,
the library whose own load/save round trip silently drops ``(comment N ...)``
nodes from a schematic's ``title_block`` (see
``kicad_mcp.schematic.sheet_pins`` for why that library was deliberately not
used to *write* sheet pins). If our text were subtly malformed, this is the
suite that would catch it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from kicad_mcp.server import build_server
from tests.conftest import call_tool_text

# ---------------------------------------------------------------------------
# Fixture project: a root schematic with a title block comment and one child
# sheet named "child", whose schematic exposes two hierarchical labels --
# VIN (input) and VOUT (output) -- for sch_import_sheet_pins to mirror.
# ---------------------------------------------------------------------------

_ROOT_TEXT = (
    "(kicad_sch\n"
    "\t(version 20250316)\n"
    '\t(generator "pytest")\n'
    '\t(uuid "00000000-0000-0000-0000-000000000000")\n'
    '\t(paper "A4")\n'
    "\t(title_block\n"
    '\t\t(title "Sheet pin import fixture")\n'
    '\t\t(comment 1 "keep me")\n'
    '\t\t(comment 2 "and me too")\n'
    "\t)\n"
    "\t(lib_symbols)\n"
    "\t(sheet\n"
    "\t\t(at 80.01 30.48)\n"
    "\t\t(size 30.48 20.32)\n"
    '\t\t(uuid "55555555-5555-5555-5555-555555555555")\n'
    '\t\t(property "Sheetname" "child"\n'
    "\t\t\t(at 80.01 29.77 0)\n"
    "\t\t\t(effects (font (size 1.27 1.27)) (justify left bottom))\n"
    "\t\t)\n"
    '\t\t(property "Sheetfile" "child.kicad_sch"\n'
    "\t\t\t(at 80.01 51.38 0)\n"
    "\t\t\t(effects (font (size 1.27 1.27)) (justify left top))\n"
    "\t\t)\n"
    "\t\t(instances\n"
    '\t\t\t(project "demo"\n'
    '\t\t\t\t(path "/1" (page "2"))\n'
    "\t\t\t)\n"
    "\t\t)\n"
    "\t)\n"
    "\t(sheet_instances\n"
    '\t\t(path "/" (page "1"))\n'
    "\t)\n"
    "\t(embedded_fonts no)\n"
    ")\n"
)

_CHILD_TEXT = (
    "(kicad_sch\n"
    "\t(version 20250316)\n"
    '\t(generator "pytest")\n'
    '\t(uuid "11111111-1111-1111-1111-111111111111")\n'
    '\t(paper "A4")\n'
    "\t(lib_symbols)\n"
    '\t(hierarchical_label "VIN"\n'
    "\t\t(shape input)\n"
    "\t\t(at 10.16 10.16 0)\n"
    "\t\t(effects (font (size 1.27 1.27)))\n"
    '\t\t(uuid "22222222-2222-2222-2222-222222222222")\n'
    "\t)\n"
    '\t(hierarchical_label "VOUT"\n'
    "\t\t(shape output)\n"
    "\t\t(at 30.48 10.16 0)\n"
    "\t\t(effects (font (size 1.27 1.27)))\n"
    '\t\t(uuid "33333333-3333-3333-3333-333333333333")\n'
    "\t)\n"
    "\t(sheet_instances\n"
    '\t\t(path "/" (page "1"))\n'
    "\t)\n"
    "\t(embedded_fonts no)\n"
    ")\n"
)


def _extract_block(text: str, tag: str) -> str:
    """Return the whole balanced ``(tag ...)`` block, matching parentheses.

    Used to compare the ``title_block`` before and after a write byte for
    byte -- not merely to check that one comment substring survived, but that
    nothing inside it was dropped, reordered, or reformatted.
    """
    start = text.index(f"({tag}")
    depth = 0
    for index in range(start, len(text)):
        char = text[index]
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    raise ValueError(f"Unbalanced '{tag}' block in schematic text.")


@pytest.fixture
def sample_hierarchical_project(sample_project: Path) -> Path:
    """A minimal hierarchical project ready for ``sch_import_sheet_pins``.

    Reuses ``sample_project`` for its library layout and env wiring, then
    overwrites ``demo.kicad_sch`` with a root schematic carrying a
    ``title_block`` comment and one child sheet named "child", and adds a
    ``child.kicad_sch`` exposing the two hierarchical labels the import must
    mirror as sheet pins.
    """
    (sample_project / "demo.kicad_sch").write_text(_ROOT_TEXT, encoding="utf-8")
    (sample_project / "child.kicad_sch").write_text(_CHILD_TEXT, encoding="utf-8")
    return sample_project


async def _open_project(sample_hierarchical_project: Path) -> object:
    """Build a schematic-profile server and point it at the fixture project.

    ``sch_file`` is passed explicitly: ``kicad_set_project`` otherwise picks
    the alphabetically-first ``*.kicad_sch`` in the directory when none
    matches the project directory's own name, which would silently select
    ``child.kicad_sch`` instead of the root ``demo.kicad_sch``.
    """
    server = build_server("schematic")
    await call_tool_text(
        server,
        "kicad_set_project",
        {
            "project_dir": str(sample_hierarchical_project),
            "sch_file": str(sample_hierarchical_project / "demo.kicad_sch"),
        },
    )
    return server


@pytest.mark.anyio
async def test_import_creates_one_pin_per_label_and_keeps_the_title_block(
    sample_hierarchical_project: Path,
    mock_kicad: object,
) -> None:
    _ = mock_kicad
    top_file = sample_hierarchical_project / "demo.kicad_sch"
    before = top_file.read_text(encoding="utf-8")
    before_title_block = _extract_block(before, "title_block")
    server = await _open_project(sample_hierarchical_project)

    report = await call_tool_text(server, "sch_import_sheet_pins", {})

    after = top_file.read_text(encoding="utf-8")
    assert '(pin "VIN" input' in after
    assert '(pin "VOUT" output' in after
    assert "- child: 2 added, 0 retyped, 0 moved, 0 unchanged" in report

    # The whole reason for the text-splice write path: everything outside the
    # sheet block -- including every (comment N ...) node -- is untouched.
    after_title_block = _extract_block(after, "title_block")
    assert after_title_block == before_title_block
    assert before.count("(comment") == after.count("(comment") == 2


@pytest.mark.anyio
async def test_imported_pins_are_readable_by_kicad_sch_api(
    sample_hierarchical_project: Path,
    mock_kicad: object,
) -> None:
    _ = mock_kicad
    import kicad_sch_api as ksa

    server = await _open_project(sample_hierarchical_project)
    await call_tool_text(server, "sch_import_sheet_pins", {})

    schematic = ksa.load_schematic(str(sample_hierarchical_project / "demo.kicad_sch"))
    sheet = schematic.sheets.get_sheet_by_name("child")
    assert sheet is not None
    pins = {pin["name"]: pin["pin_type"] for pin in schematic.sheets.list_sheet_pins(sheet["uuid"])}
    assert pins == {"VIN": "input", "VOUT": "output"}


@pytest.mark.anyio
async def test_a_second_import_changes_nothing(
    sample_hierarchical_project: Path,
    mock_kicad: object,
) -> None:
    _ = mock_kicad
    top_file = sample_hierarchical_project / "demo.kicad_sch"
    server = await _open_project(sample_hierarchical_project)
    await call_tool_text(server, "sch_import_sheet_pins", {})
    after_first = top_file.read_text(encoding="utf-8")

    report = await call_tool_text(server, "sch_import_sheet_pins", {})

    assert top_file.read_text(encoding="utf-8") == after_first
    assert "already up to date" in report.casefold()


@pytest.mark.anyio
async def test_dry_run_reports_without_writing(
    sample_hierarchical_project: Path,
    mock_kicad: object,
) -> None:
    _ = mock_kicad
    top_file = sample_hierarchical_project / "demo.kicad_sch"
    before = top_file.read_text(encoding="utf-8")
    server = await _open_project(sample_hierarchical_project)

    report = await call_tool_text(server, "sch_import_sheet_pins", {"dry_run": True})

    assert top_file.read_text(encoding="utf-8") == before
    assert "dry run" in report.casefold()


@pytest.mark.anyio
async def test_list_sheet_pins_sees_what_import_wrote(
    sample_hierarchical_project: Path,
    mock_kicad: object,
) -> None:
    _ = mock_kicad
    server = await _open_project(sample_hierarchical_project)
    await call_tool_text(server, "sch_import_sheet_pins", {})

    report = await call_tool_text(server, "sch_list_sheet_pins", {"sheet_name": "child"})

    assert "VIN" in report
    assert "VOUT" in report

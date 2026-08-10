"""End-to-end coverage: ``sch_spread_sheets`` and ``sch_wire_sheet_pins`` on a
real, hierarchical root schematic.

A sheet pin alone joins nothing. Two child sheets become one net only once
something in the *parent* schematic connects their pins -- matching names are
not enough, unlike global labels (see ``kicad_mcp.schematic.sheet_wiring``).
``sch_wire_sheet_pins`` closes that gap with a wire stub and a local label at
every pin; ``sch_spread_sheets`` makes room for those labels by moving whole
sheet-symbol columns apart. Both write through ``transactional_write`` --
never through ``kicad_sch_api`` -- because that library's own load/save round
trip silently drops ``(comment N ...)`` nodes from a schematic's
``title_block``.

The unit tests around ``kicad_mcp.schematic.sheet_wiring`` prove the emitted
text is what *we* intended. This module proves it is what *KiCad's own data
model* expects: it writes through the real tools -- the same text-splice code
path the server uses in production -- and reads the result back through
``kicad_sch_api``, the very library whose serializer this design refuses to
write with. If the text were subtly malformed, this is the suite that would
catch it.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from kicad_mcp.schematic.sheet_pins import SheetPinPlacement, parse_sheet_blocks, sheet_pin_block
from kicad_mcp.server import build_server
from tests.conftest import call_tool_text

# ---------------------------------------------------------------------------
# Fixture project: a root schematic with a title block comment and two child
# sheets, "alpha" and "beta", each already carrying one sheet pin named
# "SHARED" -- as if sch_import_sheet_pins had already mirrored a hierarchical
# label of that name out of each child. Coordinates are hand-chosen, all on
# the 1.27 mm schematic grid, so the geometry sch_spread_sheets must compute
# (the required gap, the resulting shift) is exact and known ahead of time,
# not merely "some positive number".
#
# alpha's pin sits on alpha's own right edge (rotation 0, facing right);
# beta's pin sits on beta's own left edge (rotation 180, facing left) --
# they face each other across a 3.81 mm gap, deliberately too narrow for a
# stub-and-label pair.
# ---------------------------------------------------------------------------

_ALPHA_ORIGIN = (39.37, 25.4)  # 31 x 1.27, 20 x 1.27 mm
_ALPHA_SIZE = (25.4, 15.24)  # 20 x 1.27, 12 x 1.27 mm
_BETA_ORIGIN = (68.58, 25.4)  # 54 x 1.27 mm -- 3.81 mm past alpha's right edge
_BETA_SIZE = (25.4, 15.24)
_PIN_Y = 33.02  # 26 x 1.27 mm, inside both sheets' vertical span

_ALPHA_PIN_X = _ALPHA_ORIGIN[0] + _ALPHA_SIZE[0]  # 64.77 -- alpha's right edge
_BETA_PIN_X = _BETA_ORIGIN[0]  # 68.58 -- beta's left edge

_EXPECTED_SPREAD_DX = 13.97
"""What plan_spread must compute for this geometry (verified by hand):

need = 2*stub_mm + facing_width(alpha, rot=0) + facing_width(beta, rot=180) + margin_mm
     = 2*2.54 + (6 chars * 0.6 * 1.27) + (6 chars * 0.6 * 1.27) + 2.54
     = 5.08 + 4.572 + 4.572 + 2.54 = 16.764
have = beta.x_min(68.58) - alpha.x_max(64.77) = 3.81
shift = ceil_to_grid(16.764 - 3.81, 1.27) = ceil_to_grid(12.954, 1.27) = 13.97
"""

_ALPHA_PIN = SheetPinPlacement(
    name="SHARED",
    pin_type="output",
    x_mm=_ALPHA_PIN_X,
    y_mm=_PIN_Y,
    rotation=0,
    justify="right",
    uuid="44444444-4444-4444-4444-444444444444",
    action="keep",
)
_BETA_PIN = SheetPinPlacement(
    name="SHARED",
    pin_type="input",
    x_mm=_BETA_PIN_X,
    y_mm=_PIN_Y,
    rotation=180,
    justify="left",
    uuid="66666666-6666-6666-6666-666666666666",
    action="keep",
)

_ROOT_TEMPLATE = (
    "(kicad_sch\n"
    "\t(version 20250316)\n"
    '\t(generator "pytest")\n'
    '\t(uuid "00000000-0000-0000-0000-000000000000")\n'
    '\t(paper "A4")\n'
    "\t(title_block\n"
    '\t\t(title "Root sheet wiring fixture")\n'
    '\t\t(comment 1 "keep me")\n'
    '\t\t(comment 2 "and me too")\n'
    "\t)\n"
    "\t(lib_symbols)\n"
    "\t(sheet\n"
    "\t\t(at 39.37 25.4)\n"
    "\t\t(size 25.4 15.24)\n"
    '\t\t(uuid "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")\n'
    '\t\t(property "Sheetname" "alpha"\n'
    "\t\t\t(at 39.37 24.69 0)\n"
    "\t\t\t(effects (font (size 1.27 1.27)) (justify left bottom))\n"
    "\t\t)\n"
    '\t\t(property "Sheetfile" "alpha.kicad_sch"\n'
    "\t\t\t(at 39.37 41.35 0)\n"
    "\t\t\t(effects (font (size 1.27 1.27)) (justify left top))\n"
    "\t\t)\n"
    "{alpha_pin}"
    "\t\t(instances\n"
    '\t\t\t(project "demo"\n'
    '\t\t\t\t(path "/1" (page "2"))\n'
    "\t\t\t)\n"
    "\t\t)\n"
    "\t)\n"
    "\t(sheet\n"
    "\t\t(at 68.58 25.4)\n"
    "\t\t(size 25.4 15.24)\n"
    '\t\t(uuid "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")\n'
    '\t\t(property "Sheetname" "beta"\n'
    "\t\t\t(at 68.58 24.69 0)\n"
    "\t\t\t(effects (font (size 1.27 1.27)) (justify left bottom))\n"
    "\t\t)\n"
    '\t\t(property "Sheetfile" "beta.kicad_sch"\n'
    "\t\t\t(at 68.58 41.35 0)\n"
    "\t\t\t(effects (font (size 1.27 1.27)) (justify left top))\n"
    "\t\t)\n"
    "{beta_pin}"
    "\t\t(instances\n"
    '\t\t\t(project "demo"\n'
    '\t\t\t\t(path "/2" (page "3"))\n'
    "\t\t\t)\n"
    "\t\t)\n"
    "\t)\n"
    "\t(sheet_instances\n"
    '\t\t(path "/" (page "1"))\n'
    "\t)\n"
    "\t(embedded_fonts no)\n"
    ")\n"
)


def _root_text() -> str:
    """Render the fixture root schematic, using the real pin emitter.

    The two ``(pin ...)`` blocks come from ``sheet_pin_block`` -- the same
    function ``sch_import_sheet_pins`` itself calls -- rather than hand-typed
    text, so the fixture's pins are byte-for-byte what that tool would have
    written, without re-testing import here (that is
    ``test_schematic_sheet_pin_import.py``'s job).
    """
    return _ROOT_TEMPLATE.format(
        alpha_pin=sheet_pin_block(_ALPHA_PIN),
        beta_pin=sheet_pin_block(_BETA_PIN),
    )


def _extract_block(text: str, tag: str) -> str:
    """Return the whole balanced ``(tag ...)`` block, matching parentheses.

    Used to compare a block before and after a write byte for byte -- not
    merely to check that a substring survived, but that nothing inside it was
    dropped, reordered, or reformatted.
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


def _pin_effects(text: str, name: str, pin_type: str) -> str:
    """Return the ``(effects ...)`` block of one named, typed sheet pin."""
    pin_block = _extract_block(text, f'pin "{name}" {pin_type}')
    return _extract_block(pin_block, "effects")


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@pytest.fixture
def sample_root_wiring_project(sample_project: Path) -> Path:
    """A two-sheet hierarchical project, each sheet already pin-mirrored.

    Reuses ``sample_project`` for its library layout and env wiring, then
    overwrites ``demo.kicad_sch`` with the root schematic described above.
    """
    (sample_project / "demo.kicad_sch").write_text(_root_text(), encoding="utf-8")
    return sample_project


async def _open_project(project_dir: Path) -> object:
    """Build a schematic-profile server and point it at the fixture project.

    ``sch_file`` is passed explicitly: ``kicad_set_project`` otherwise picks
    the alphabetically-first ``*.kicad_sch`` in the directory when none
    matches the project directory's own name, which would silently select a
    child sheet instead of the root ``demo.kicad_sch``.
    """
    server = build_server("schematic")
    await call_tool_text(
        server,
        "kicad_set_project",
        {
            "project_dir": str(project_dir),
            "sch_file": str(project_dir / "demo.kicad_sch"),
        },
    )
    return server


async def _spread_then_wire(server: object) -> tuple[str, str]:
    """Run the two tools in the order the design mandates.

    ``sch_spread_sheets`` must run first: once a pin is wired,
    ``sch_spread_sheets`` refuses to move any sheet with a wire on one of its
    pins (see ``test_spread_after_wiring_refuses_and_names_the_blocking_sheet``).
    """
    spread_report = await call_tool_text(server, "sch_spread_sheets", {})
    wire_report = await call_tool_text(server, "sch_wire_sheet_pins", {})
    return spread_report, wire_report


# ---------------------------------------------------------------------------
# sch_spread_sheets
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_spread_sheets_moves_the_sheet_and_its_pin_by_the_same_delta(
    sample_root_wiring_project: Path,
    mock_kicad: object,
) -> None:
    _ = mock_kicad
    top_file = sample_root_wiring_project / "demo.kicad_sch"
    before_text = top_file.read_text(encoding="utf-8")
    before_title_block = _extract_block(before_text, "title_block")
    before_beta_effects = _pin_effects(before_text, "SHARED", "input")
    before_blocks = {block.name: block for block in parse_sheet_blocks(before_text)}

    server = await _open_project(sample_root_wiring_project)
    report = await call_tool_text(server, "sch_spread_sheets", {})

    after_text = top_file.read_text(encoding="utf-8")
    after_blocks = {block.name: block for block in parse_sheet_blocks(after_text)}

    assert "Spread 1 sheet(s): beta." in report

    # alpha is the first column: it never has to move.
    assert after_blocks["alpha"].origin == before_blocks["alpha"].origin

    sheet_dx = round(after_blocks["beta"].origin[0] - before_blocks["beta"].origin[0], 4)
    assert sheet_dx == _EXPECTED_SPREAD_DX

    beta_pin_before = before_blocks["beta"].pins[0]
    beta_pin_after = after_blocks["beta"].pins[0]
    pin_dx = round(beta_pin_after.x_mm - beta_pin_before.x_mm, 4)
    assert pin_dx == sheet_dx, "the sheet and its pin must move by exactly the same delta"
    assert beta_pin_after.y_mm == beta_pin_before.y_mm
    assert beta_pin_after.rotation == beta_pin_before.rotation == 180
    assert beta_pin_after.name == beta_pin_before.name == "SHARED"
    assert beta_pin_after.pin_type == beta_pin_before.pin_type == "input"

    # Only the pin's (at ...) node was touched -- its (effects ...) block,
    # including styling and justification, survives as identical text.
    after_beta_effects = _pin_effects(after_text, "SHARED", "input")
    assert after_beta_effects == before_beta_effects

    after_title_block = _extract_block(after_text, "title_block")
    assert after_title_block == before_title_block
    assert before_text.count("(comment") == after_text.count("(comment") == 2


@pytest.mark.anyio
async def test_a_second_spread_changes_nothing(
    sample_root_wiring_project: Path,
    mock_kicad: object,
) -> None:
    _ = mock_kicad
    top_file = sample_root_wiring_project / "demo.kicad_sch"
    server = await _open_project(sample_root_wiring_project)
    await call_tool_text(server, "sch_spread_sheets", {})
    hash_after_first = _sha256(top_file.read_text(encoding="utf-8"))

    report = await call_tool_text(server, "sch_spread_sheets", {})

    assert _sha256(top_file.read_text(encoding="utf-8")) == hash_after_first
    assert "already spread out" in report.casefold()
    assert "nothing was written" in report.casefold()


@pytest.mark.anyio
async def test_spread_after_wiring_refuses_and_names_the_blocking_sheet(
    sample_root_wiring_project: Path,
    mock_kicad: object,
) -> None:
    _ = mock_kicad
    top_file = sample_root_wiring_project / "demo.kicad_sch"
    server = await _open_project(sample_root_wiring_project)

    # Wired out of the documented order, before any spread -- the columns are
    # still only 3.81 mm apart, so a spread is still needed and must now be
    # refused rather than silently disconnect beta's freshly-added wire.
    await call_tool_text(server, "sch_wire_sheet_pins", {})
    before = top_file.read_text(encoding="utf-8")

    report = await call_tool_text(server, "sch_spread_sheets", {})

    after = top_file.read_text(encoding="utf-8")
    assert after == before, "a refused spread must not write anything"
    assert "Nothing was moved." in report
    assert "No sheet was moved: beta already has a wire on a pin" in report
    assert "alpha" not in report, "alpha never has to move, so it must not be named as a blocker"


# ---------------------------------------------------------------------------
# sch_wire_sheet_pins
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_wire_sheet_pins_adds_two_stubs_and_matching_local_labels(
    sample_root_wiring_project: Path,
    mock_kicad: object,
) -> None:
    _ = mock_kicad
    top_file = sample_root_wiring_project / "demo.kicad_sch"
    before_title_block = _extract_block(top_file.read_text(encoding="utf-8"), "title_block")
    server = await _open_project(sample_root_wiring_project)

    _, wire_report = await _spread_then_wire(server)

    after = top_file.read_text(encoding="utf-8")
    assert after.count("\t(wire\n") == 2
    assert after.count('(label "SHARED"') == 2
    assert "Wired 2 sheet pin(s): added 2 stub(s) and labels." in wire_report

    # The title block must survive this write exactly as it survived the
    # spread -- byte-identical, not merely "still has a title".
    assert _extract_block(after, "title_block") == before_title_block


@pytest.mark.anyio
async def test_a_second_wire_changes_nothing(
    sample_root_wiring_project: Path,
    mock_kicad: object,
) -> None:
    _ = mock_kicad
    top_file = sample_root_wiring_project / "demo.kicad_sch"
    server = await _open_project(sample_root_wiring_project)
    await _spread_then_wire(server)
    hash_after_first = _sha256(top_file.read_text(encoding="utf-8"))

    report = await call_tool_text(server, "sch_wire_sheet_pins", {})

    assert _sha256(top_file.read_text(encoding="utf-8")) == hash_after_first
    assert "already wired" in report.casefold()
    assert "nothing was written" in report.casefold()


# ---------------------------------------------------------------------------
# kicad_sch_api round trip
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_kicad_sch_api_reads_back_pins_wires_and_labels(
    sample_root_wiring_project: Path,
    mock_kicad: object,
) -> None:
    _ = mock_kicad
    import kicad_sch_api as ksa

    server = await _open_project(sample_root_wiring_project)
    await _spread_then_wire(server)

    schematic = ksa.load_schematic(str(sample_root_wiring_project / "demo.kicad_sch"))

    alpha = schematic.sheets.get_sheet_by_name("alpha")
    beta = schematic.sheets.get_sheet_by_name("beta")
    assert alpha is not None
    assert beta is not None

    alpha_pins = {
        pin["name"]: pin["pin_type"] for pin in schematic.sheets.list_sheet_pins(alpha["uuid"])
    }
    beta_pins = {
        pin["name"]: pin["pin_type"] for pin in schematic.sheets.list_sheet_pins(beta["uuid"])
    }
    # Not a count: the name AND the type of each pin, so a bug that read back
    # every pin as "input" (or dropped the name) would fail this.
    assert alpha_pins == {"SHARED": "output"}
    assert beta_pins == {"SHARED": "input"}

    # The stub wires and local labels sch_wire_sheet_pins wrote also parse.
    assert len(schematic.wires) == 2
    label_texts = [label.text for label in schematic.labels]
    assert label_texts == ["SHARED", "SHARED"]

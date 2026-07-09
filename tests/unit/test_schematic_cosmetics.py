"""Unit tests for schematic cosmetic auto-fixers (Visual Excellence Loop, Phase B).

The safety-critical assertion throughout is **connectivity preservation**: a
fixer may move geometry, but it must never change which pins/labels are
electrically common. Core tests use wire+label connectivity so they run without a
KiCad symbol library; pin-dependent tests are guarded.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from kicad_mcp.tools.schematic import _symbol_library_file
from kicad_mcp.tools.schematic_cosmetics import (
    _connectivity_signature,
    _flip_justify,
    _mutate_align_to_grid,
    _mutate_normalize_power_orientation,
    _mutate_normalize_text_sizes,
    _mutate_resolve_label_overlaps,
    _mutate_straighten_wires,
)

_HAS_SYS_SYMBOLS = _symbol_library_file("power") is not None


# ---------------------------------------------------------------------------
# Connectivity signature invariant
# ---------------------------------------------------------------------------


def test_signature_is_coordinate_independent() -> None:
    """A pure translation of a connected net leaves the signature unchanged."""
    at_a = '(kicad_sch (wire (pts (xy 10 10) (xy 10 20))) (label "N1" (at 10 15 0)))'
    at_b = '(kicad_sch (wire (pts (xy 30 40) (xy 30 50))) (label "N1" (at 30 45 0)))'
    assert _connectivity_signature(at_a) == _connectivity_signature(at_b)


def test_signature_detects_detached_label() -> None:
    """Moving a label off its wire splits the net and changes the signature."""
    connected = '(kicad_sch (wire (pts (xy 10 10) (xy 10 20))) (label "N1" (at 10 15 0)))'
    detached = '(kicad_sch (wire (pts (xy 10 10) (xy 10 20))) (label "N1" (at 99 99 0)))'
    assert _connectivity_signature(connected) != _connectivity_signature(detached)


# ---------------------------------------------------------------------------
# Pure mutators
# ---------------------------------------------------------------------------

_OFF_GRID_SCH = """(kicad_sch
  (wire (pts (xy 50.7 40.0) (xy 50.7 50.1)))
  (junction (at 50.7 45.0))
  (label "N1" (at 50.7 45.0 0))
  (symbol (lib_id "Device:R") (at 50.7 36.83 0)
    (property "Reference" "R1" (at 53 35 0)))
)"""


def test_align_to_grid_snaps_all_object_kinds() -> None:
    after, changes = _mutate_align_to_grid(_OFF_GRID_SCH)
    kinds = {change["kind"] for change in changes}
    assert kinds == {"symbol", "label", "junction", "wire"}
    # Every anchor now lands on a 1.27 mm multiple.
    assert "50.7" not in after


def test_align_to_grid_noop_when_on_grid() -> None:
    on_grid = '(kicad_sch (label "N1" (at 50.8 45.72 0)))'
    _, changes = _mutate_align_to_grid(on_grid)
    assert changes == []


def test_straighten_wires_flattens_near_orthogonal() -> None:
    sch = "(kicad_sch (wire (pts (xy 10 10) (xy 30 10.3))))"
    after, changes = _mutate_straighten_wires(sch)
    assert len(changes) == 1
    assert changes[0]["to"] == [30.0, 10.0]
    # A clearly diagonal run is left alone.
    diagonal = "(kicad_sch (wire (pts (xy 10 10) (xy 30 25))))"
    _, none = _mutate_straighten_wires(diagonal)
    assert none == []


def test_normalize_text_sizes_targets_outliers_only() -> None:
    sch = """(kicad_sch
      (label "A" (at 10 10 0) (effects (font (size 1.27 1.27))))
      (label "B" (at 20 20 0) (effects (font (size 1.27 1.27))))
      (label "C" (at 30 30 0) (effects (font (size 2.54 2.54))))
    )"""
    after, changes = _mutate_normalize_text_sizes(sch)
    assert len(changes) == 1
    assert "2.54" not in after


def test_normalize_text_sizes_ignores_lib_symbols_cache() -> None:
    sch = """(kicad_sch
      (lib_symbols (symbol "Device:R" (symbol "R_1_1"
        (pin passive line (at 0 0 0) (length 1)
          (name "~" (effects (font (size 5 5)))) (number "1")))))
      (label "A" (at 10 10 0) (effects (font (size 1.27 1.27))))
      (label "B" (at 20 20 0) (effects (font (size 1.27 1.27))))
    )"""
    _, changes = _mutate_normalize_text_sizes(sch)
    # The 5 mm cache font is not the dominant instance size and must be untouched.
    assert changes == []


def test_resolve_label_overlaps_flips_justify_without_moving_anchor() -> None:
    sch = """(kicad_sch
      (label "OVER" (at 80 60 0) (effects (font (size 1.27 1.27))))
      (label "OVER2" (at 80.2 60 0) (effects (font (size 1.27 1.27))))
    )"""
    after, changes = _mutate_resolve_label_overlaps(sch)
    assert changes  # at least one label flipped
    # Anchors are unchanged — connectivity is preserved by construction.
    assert "(at 80 60 0)" in after
    assert _connectivity_signature(sch) == _connectivity_signature(after)


def test_flip_justify_transitions() -> None:
    assert _flip_justify("") == "left"
    assert _flip_justify("left") == "right"
    assert _flip_justify("right") == "left"
    assert _flip_justify("left top") == "right top"


@pytest.mark.skipif(not _HAS_SYS_SYMBOLS, reason="requires KiCad symbol libraries")
def test_power_orientation_preserves_pin_and_uprights() -> None:
    sch = """(kicad_sch
      (wire (pts (xy 100 100) (xy 100 110)))
      (symbol (lib_id "power:GND") (at 100 100 90)
        (property "Reference" "#PWR01" (at 100 100 0)))
    )"""
    after, changes = _mutate_normalize_power_orientation(sch)
    assert len(changes) == 1
    assert changes[0]["to_angle"] == 0
    # The GND pin sits at the symbol origin (length 0), so uprighting keeps it on
    # its wire endpoint — connectivity must be identical.
    assert _connectivity_signature(sch) == _connectivity_signature(after)


# ---------------------------------------------------------------------------
# Harness: dry-run / apply / refuse (via the live server + project)
# ---------------------------------------------------------------------------


async def _set_project(server: object, project: Path) -> None:
    from tests.conftest import call_tool_text

    await call_tool_text(server, "kicad_set_project", {"project_dir": str(project)})


@pytest.mark.anyio
@pytest.mark.mcp_mode("write")
async def test_align_dry_run_does_not_write(sample_project: Path) -> None:
    from kicad_mcp.server import build_server
    from tests.conftest import call_tool_text

    sch = sample_project / "demo.kicad_sch"
    sch.write_text(
        '(kicad_sch (paper "A4") (lib_symbols)\n'
        "  (wire (pts (xy 50.7 40.0) (xy 50.7 50.1)))\n"
        '  (label "N1" (at 50.7 45.0 0))\n)',
        encoding="utf-8",
    )
    before = sch.read_text(encoding="utf-8")

    server = build_server("schematic")
    await _set_project(server, sample_project)
    raw = await call_tool_text(server, "sch_align_to_grid", {})
    payload = json.loads(raw)

    assert payload["status"] == "dry_run"
    assert payload["connectivity_preserved"] is True
    assert payload["change_count"] >= 1
    assert sch.read_text(encoding="utf-8") == before  # nothing written


@pytest.mark.anyio
@pytest.mark.mcp_mode("write")
async def test_align_apply_writes_on_grid(sample_project: Path) -> None:
    from kicad_mcp.server import build_server
    from tests.conftest import call_tool_text

    sch = sample_project / "demo.kicad_sch"
    sch.write_text(
        '(kicad_sch (paper "A4") (lib_symbols)\n'
        "  (wire (pts (xy 50.7 40.0) (xy 50.7 50.1)))\n"
        '  (label "N1" (at 50.7 45.0 0))\n)',
        encoding="utf-8",
    )

    server = build_server("schematic")
    await _set_project(server, sample_project)
    raw = await call_tool_text(server, "sch_align_to_grid", {"apply": True})
    payload = json.loads(raw)

    assert payload["status"] == "applied"
    assert "50.7" not in sch.read_text(encoding="utf-8")  # snapped on disk


@pytest.mark.anyio
@pytest.mark.mcp_mode("write")
async def test_harness_refuses_connectivity_breaking_mutation(sample_project: Path) -> None:
    from kicad_mcp.server import build_server
    from kicad_mcp.tools import schematic_cosmetics as sc

    sch = sample_project / "demo.kicad_sch"
    sch.write_text(
        '(kicad_sch (paper "A4") (lib_symbols)\n'
        "  (wire (pts (xy 50.8 40.64) (xy 50.8 50.8)))\n"
        '  (label "N1" (at 50.8 45.72 0))\n)',
        encoding="utf-8",
    )
    before = sch.read_text(encoding="utf-8")

    server = build_server("schematic")
    await _set_project(server, sample_project)

    def _breaking_mutator(text: str) -> tuple[str, list[dict[str, object]]]:
        # Move the label off the wire — this splits the net.
        broken = text.replace("(at 50.8 45.72 0)", "(at 12.7 190.5 0)")
        return broken, [{"kind": "label", "ref": "N1"}]

    raw = sc._run_cosmetic_fix("test_break", _breaking_mutator, apply=True)
    payload = json.loads(raw)

    assert payload["status"] == "refused"
    assert payload["connectivity_preserved"] is False
    assert sch.read_text(encoding="utf-8") == before  # nothing written


@pytest.mark.anyio
@pytest.mark.mcp_mode("write")
@pytest.mark.parametrize(
    "tool_name",
    [
        "sch_align_to_grid",
        "sch_straighten_wires",
        "sch_resolve_label_overlaps",
        "sch_normalize_power_orientation",
        "sch_normalize_text_sizes",
    ],
)
async def test_every_fixer_dry_runs_cleanly(sample_project: Path, tool_name: str) -> None:
    """Each fixer answers a dry run with a structured, non-writing report."""
    from kicad_mcp.server import build_server
    from tests.conftest import call_tool_text

    sch = sample_project / "demo.kicad_sch"
    sch.write_text(
        '(kicad_sch (paper "A4") (lib_symbols)\n'
        "  (wire (pts (xy 50.7 40.0) (xy 50.7 50.1)))\n"
        '  (label "N1" (at 50.7 45.0 0) (effects (font (size 1.27 1.27))))\n)',
        encoding="utf-8",
    )
    before = sch.read_text(encoding="utf-8")

    server = build_server("schematic")
    await _set_project(server, sample_project)
    raw = await call_tool_text(server, tool_name, {})
    payload = json.loads(raw)

    assert payload["fix"] == tool_name
    assert payload["status"] in {"dry_run", "no_change"}
    assert sch.read_text(encoding="utf-8") == before  # dry run never writes

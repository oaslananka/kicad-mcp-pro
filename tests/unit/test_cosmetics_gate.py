"""Unit tests for the advisory schematic-cosmetics quality gate (Phase E)."""

from __future__ import annotations

from pathlib import Path

import pytest

from kicad_mcp.tools.fixers import BLOCKING_GATES, GATE_FIXERS, fixers_for_gate

_CLEAN_SCH = """(kicad_sch (paper "A4")
  (title_block (title "Clean") (rev "A") (date "2026-01-01") (company "Acme"))
  (wire (pts (xy 50.8 50.8) (xy 63.5 50.8)))
  (label "NET_A" (at 50.8 40.64 0) (effects (font (size 1.27 1.27))))
)"""

_UGLY_SCH = """(kicad_sch (paper "A4")
  (wire (pts (xy 50.7 40.0) (xy 63.4 40.3)))
  (label "NET_A" (at 50.7 40.0 0) (effects (font (size 2.54 2.54))))
  (label "NET_B" (at 63.4 40.3 0) (effects (font (size 1.27 1.27))))
  (junction (at 50.7 40.0))
)"""


def test_cosmetics_gate_is_advisory_and_suggest_only() -> None:
    # The gate must never block release, and its fixers are suggestions only.
    assert "Schematic cosmetics" not in BLOCKING_GATES
    fixers = fixers_for_gate("Schematic cosmetics")
    assert fixers, "cosmetics gate should have fixer suggestions"
    assert all(not fixer.auto_applicable for fixer in fixers)
    tools = {fixer.tool for fixer in fixers}
    assert "sch_align_to_grid" in tools
    assert "sch_cosmetic_score" in tools


def test_cosmetics_gate_fixers_have_no_broken_callables() -> None:
    from kicad_mcp.tools.fixers import validate_callable_imports

    assert validate_callable_imports(GATE_FIXERS) == []


@pytest.mark.anyio
@pytest.mark.mcp_mode("write")
async def test_cosmetics_gate_passes_on_clean_sheet(sample_project: Path) -> None:
    from kicad_mcp.server import build_server
    from kicad_mcp.tools.validation import _evaluate_schematic_cosmetics_gate
    from tests.conftest import call_tool_text

    (sample_project / "demo.kicad_sch").write_text(_CLEAN_SCH, encoding="utf-8")
    server = build_server("schematic")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    outcome = _evaluate_schematic_cosmetics_gate()
    assert outcome.name == "Schematic cosmetics"
    assert outcome.status == "PASS"


@pytest.mark.anyio
@pytest.mark.mcp_mode("write")
async def test_cosmetics_gate_warns_on_ugly_sheet(sample_project: Path) -> None:
    from kicad_mcp.server import build_server
    from kicad_mcp.tools.validation import _evaluate_schematic_cosmetics_gate
    from tests.conftest import call_tool_text

    (sample_project / "demo.kicad_sch").write_text(_UGLY_SCH, encoding="utf-8")
    server = build_server("schematic")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    outcome = _evaluate_schematic_cosmetics_gate()
    assert outcome.status == "WARN"
    assert "does not block release" in outcome.summary


@pytest.mark.anyio
@pytest.mark.mcp_mode("write")
async def test_cosmetics_gate_included_in_project_gate(sample_project: Path) -> None:
    from kicad_mcp.server import build_server
    from kicad_mcp.tools.validation import _evaluate_project_gate
    from tests.conftest import call_tool_text

    (sample_project / "demo.kicad_sch").write_text(_CLEAN_SCH, encoding="utf-8")
    server = build_server("schematic")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    names = {outcome.name for outcome in _evaluate_project_gate()}
    assert "Schematic cosmetics" in names

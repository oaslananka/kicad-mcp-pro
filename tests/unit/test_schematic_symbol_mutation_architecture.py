from __future__ import annotations

from scripts import check_architecture_boundaries as boundaries
from tests.architecture_source_helpers import _function_span, _imports


def test_architecture_checker_tracks_symbol_mutation_modules() -> None:
    assert "kicad_mcp.schematic.symbol_mutation" in boundaries.DOMAIN_MODULES
    assert "kicad_mcp.schematic.symbol_mutation" in boundaries.PURE_HELPERS
    assert "kicad_mcp.tools.schematic_symbol_mutation" in boundaries.DOMAIN_MODULES


def test_symbol_mutation_adapter_does_not_import_monolith() -> None:
    adapter = boundaries.SRC_ROOT / "kicad_mcp" / "tools" / "schematic_symbol_mutation.py"
    assert "kicad_mcp.tools.schematic" not in _imports(adapter)


def test_symbol_mutation_register_stays_below_300_lines() -> None:
    adapter = boundaries.SRC_ROOT / "kicad_mcp" / "tools" / "schematic_symbol_mutation.py"
    assert _function_span(adapter, "register") <= 300
    assert boundaries.REGISTER_LINE_LIMITS["kicad_mcp.tools.schematic_symbol_mutation"] == 300

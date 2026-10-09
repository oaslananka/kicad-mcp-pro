from __future__ import annotations

from scripts import check_architecture_boundaries as boundaries
from tests.architecture_source_helpers import _function_span, _imports


def test_architecture_checker_tracks_schematic_inspection_modules() -> None:
    assert "kicad_mcp.schematic.inspection" in boundaries.DOMAIN_MODULES
    assert "kicad_mcp.schematic.inspection" in boundaries.PURE_HELPERS
    assert "kicad_mcp.tools.schematic_inspection" in boundaries.DOMAIN_MODULES


def test_schematic_inspection_adapter_does_not_import_monolith() -> None:
    adapter = boundaries.SRC_ROOT / "kicad_mcp" / "tools" / "schematic_inspection.py"
    assert "kicad_mcp.tools.schematic" not in _imports(adapter)


def test_schematic_inspection_register_stays_below_300_lines() -> None:
    adapter = boundaries.SRC_ROOT / "kicad_mcp" / "tools" / "schematic_inspection.py"
    assert _function_span(adapter, "register") <= 300
    assert boundaries.REGISTER_LINE_LIMITS["kicad_mcp.tools.schematic_inspection"] == 300

from __future__ import annotations

from scripts import check_architecture_boundaries as boundaries
from tests.architecture_source_helpers import _function_span, _imports


def test_architecture_checker_tracks_semantic_ir_modules() -> None:
    assert "kicad_mcp.schematic.semantic_ir" in boundaries.DOMAIN_MODULES
    assert "kicad_mcp.schematic.semantic_ir" in boundaries.PURE_HELPERS
    assert "kicad_mcp.tools.schematic_semantic_ir" in boundaries.DOMAIN_MODULES


def test_semantic_ir_adapter_does_not_import_monolith() -> None:
    adapter = boundaries.SRC_ROOT / "kicad_mcp" / "tools" / "schematic_semantic_ir.py"
    assert "kicad_mcp.tools.schematic" not in _imports(adapter)
    assert boundaries.ADAPTER_FORBIDDEN_IMPORT_PREFIXES[
        "kicad_mcp.tools.schematic_semantic_ir"
    ] == ("kicad_mcp.tools.schematic",)


def test_semantic_ir_register_stays_below_300_lines() -> None:
    adapter = boundaries.SRC_ROOT / "kicad_mcp" / "tools" / "schematic_semantic_ir.py"
    assert _function_span(adapter, "register") <= 300
    assert boundaries.REGISTER_LINE_LIMITS["kicad_mcp.tools.schematic_semantic_ir"] == 300

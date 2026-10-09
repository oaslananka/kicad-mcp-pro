from __future__ import annotations

import ast

from scripts import check_architecture_boundaries as boundaries
from tests.architecture_source_helpers import _function_span, _imports


def test_architecture_checker_tracks_export_drill_modules() -> None:
    assert "kicad_mcp.export.drill" in boundaries.DOMAIN_MODULES
    assert "kicad_mcp.export.drill" in boundaries.PURE_HELPERS
    assert "kicad_mcp.tools.export_drill" in boundaries.DOMAIN_MODULES


def test_export_drill_adapter_does_not_import_monolith() -> None:
    adapter = boundaries.SRC_ROOT / "kicad_mcp" / "tools" / "export_drill.py"
    assert adapter.exists()
    assert "kicad_mcp.tools.export" not in _imports(adapter)


def test_export_drill_register_stays_below_100_lines() -> None:
    adapter = boundaries.SRC_ROOT / "kicad_mcp" / "tools" / "export_drill.py"
    assert adapter.exists()
    assert _function_span(adapter, "register") <= 100
    assert boundaries.REGISTER_LINE_LIMITS["kicad_mcp.tools.export_drill"] == 100


def test_export_composition_root_no_longer_owns_drill_tools() -> None:
    root = boundaries.SRC_ROOT / "kicad_mcp" / "tools" / "export.py"
    tree = ast.parse(root.read_text(encoding="utf-8"), filename=str(root))
    register_node = next(
        node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "register"
    )
    nested = {
        node.name
        for node in register_node.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert nested.isdisjoint({"_export_drill", "export_drill"})

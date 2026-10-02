from __future__ import annotations

import ast

from scripts import check_architecture_boundaries as boundaries

IMPORT_TOOL_NAMES = {
    "mfg_check_import_support",
    "pcb_import_board",
    "mfg_import_allegro",
    "mfg_import_pads",
    "mfg_import_geda",
    "mfg_import_specctra",
}


def test_architecture_checker_tracks_manufacturing_import_modules() -> None:
    assert "kicad_mcp.manufacturing.imports" in boundaries.DOMAIN_MODULES
    assert "kicad_mcp.manufacturing.imports" in boundaries.PURE_HELPERS
    assert "kicad_mcp.tools.manufacturing_imports" in boundaries.DOMAIN_MODULES


def test_manufacturing_import_adapter_stays_thin_and_away_from_root_monolith() -> None:
    module_name = "kicad_mcp.tools.manufacturing_imports"
    adapter = boundaries.DOMAIN_MODULES[module_name]
    assert "kicad_mcp.tools.manufacturing" not in boundaries._imports_for(module_name, adapter)
    span = boundaries._function_span(adapter, "register")
    assert span is not None
    assert span <= 150
    assert boundaries.REGISTER_LINE_LIMITS[module_name] == 150


def test_manufacturing_root_delegates_import_tools_and_shrinks() -> None:
    root = boundaries.SRC_ROOT / "kicad_mcp" / "tools" / "manufacturing.py"
    tree = ast.parse(root.read_text(encoding="utf-8"), filename=str(root))
    register_node = next(
        node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "register"
    )
    nested = {
        node.name
        for node in register_node.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }

    assert IMPORT_TOOL_NAMES.isdisjoint(nested)
    span = boundaries._function_span(root, "register")
    assert span is not None
    assert span <= 875

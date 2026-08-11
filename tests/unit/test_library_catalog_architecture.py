from __future__ import annotations

import ast

from scripts import check_architecture_boundaries as boundaries

OWNED_FUNCTIONS = {
    "lib_list_libraries",
    "lib_search_symbols",
    "lib_get_symbol_info",
    "lib_search_footprints",
    "lib_list_footprints",
    "lib_rebuild_index",
    "lib_get_footprint_info",
    "lib_get_footprint_3d_model",
}


def test_architecture_checker_tracks_library_catalog_modules() -> None:
    assert "kicad_mcp.library.catalog" in boundaries.DOMAIN_MODULES
    assert "kicad_mcp.library.catalog" in boundaries.PURE_HELPERS
    assert "kicad_mcp.tools.library_catalog" in boundaries.DOMAIN_MODULES


def test_library_catalog_adapter_does_not_import_library_monolith() -> None:
    module_name = "kicad_mcp.tools.library_catalog"
    adapter = boundaries.DOMAIN_MODULES[module_name]
    assert "kicad_mcp.tools.library" not in boundaries._imports_for(module_name, adapter)


def test_library_catalog_register_stays_below_reviewed_limit() -> None:
    module_name = "kicad_mcp.tools.library_catalog"
    span = boundaries._function_span(boundaries.DOMAIN_MODULES[module_name], "register")
    assert span is not None
    assert span <= 160
    assert boundaries.REGISTER_LINE_LIMITS[module_name] == 160


def test_library_root_no_longer_owns_catalog_tools() -> None:
    root = boundaries.SRC_ROOT / "kicad_mcp" / "tools" / "library.py"
    tree = ast.parse(root.read_text(encoding="utf-8"), filename=str(root))
    register_node = next(
        node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "register"
    )
    nested_names = {
        node.name
        for node in register_node.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert nested_names.isdisjoint(OWNED_FUNCTIONS)

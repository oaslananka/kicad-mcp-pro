from __future__ import annotations

import ast

from scripts import check_architecture_boundaries as boundaries

OWNED_FUNCTIONS = {
    "lib_search_components",
    "lib_get_component_details",
    "lib_check_sourcing_policy",
    "lib_assign_lcsc_to_symbol",
    "lib_get_bom_with_pricing",
    "lib_check_stock_availability",
    "lib_find_alternative_parts",
    "lib_recommend_part",
    "lib_bind_part_to_symbol",
}


def test_architecture_checker_tracks_library_sourcing_modules() -> None:
    assert "kicad_mcp.library.sourcing" in boundaries.DOMAIN_MODULES
    assert "kicad_mcp.library.sourcing" in boundaries.PURE_HELPERS
    assert "kicad_mcp.tools.library_sourcing" in boundaries.DOMAIN_MODULES


def test_library_sourcing_adapter_does_not_import_library_monolith() -> None:
    module_name = "kicad_mcp.tools.library_sourcing"
    adapter = boundaries.DOMAIN_MODULES[module_name]
    assert "kicad_mcp.tools.library" not in boundaries._imports_for(module_name, adapter)


def test_library_sourcing_register_stays_below_reviewed_limit() -> None:
    module_name = "kicad_mcp.tools.library_sourcing"
    span = boundaries._function_span(boundaries.DOMAIN_MODULES[module_name], "register")
    assert span is not None
    assert span <= 180
    assert boundaries.REGISTER_LINE_LIMITS[module_name] == 180


def test_library_root_no_longer_owns_sourcing_tools() -> None:
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


def test_library_sourcing_part_selection_register_stays_bounded() -> None:
    module_name = "kicad_mcp.tools.library_sourcing"
    span = boundaries._function_span(
        boundaries.DOMAIN_MODULES[module_name], "register_part_selection"
    )
    assert span is not None
    assert span <= 100


def test_library_sourcing_bind_part_stays_thin() -> None:
    import ast

    service = boundaries.SRC_ROOT / "kicad_mcp" / "library" / "sourcing.py"
    tree = ast.parse(service.read_text(encoding="utf-8"), filename=str(service))
    service_class = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "LibrarySourcingService"
    )
    method = next(
        node
        for node in service_class.body
        if isinstance(node, ast.FunctionDef) and node.name == "bind_part_to_symbol"
    )
    assert method.end_lineno is not None
    assert method.end_lineno - method.lineno + 1 <= 45

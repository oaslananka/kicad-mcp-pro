from __future__ import annotations

import ast

from scripts import check_architecture_boundaries as boundaries

OWNED_FUNCTIONS = {"lib_assign_footprint", "lib_create_custom_symbol"}


def test_architecture_checker_tracks_library_local_authoring_modules() -> None:
    assert "kicad_mcp.library.local_authoring" in boundaries.DOMAIN_MODULES
    assert "kicad_mcp.library.local_authoring" in boundaries.PURE_HELPERS
    assert "kicad_mcp.tools.library_local_authoring" in boundaries.DOMAIN_MODULES


def test_local_authoring_adapter_does_not_import_library_monolith() -> None:
    module_name = "kicad_mcp.tools.library_local_authoring"
    adapter = boundaries.DOMAIN_MODULES[module_name]
    assert "kicad_mcp.tools.library" not in boundaries._imports_for(module_name, adapter)


def test_local_authoring_register_stays_below_reviewed_limit() -> None:
    module_name = "kicad_mcp.tools.library_local_authoring"
    span = boundaries._function_span(boundaries.DOMAIN_MODULES[module_name], "register")
    assert span is not None
    assert span <= 100
    assert boundaries.REGISTER_LINE_LIMITS[module_name] == 100


def test_library_root_no_longer_owns_local_authoring_tools() -> None:
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


def test_pin_table_generator_registration_stays_bounded() -> None:
    module = boundaries.DOMAIN_MODULES["kicad_mcp.tools.library_local_authoring"]
    span = boundaries._function_span(module, "register_pin_table_generator")
    assert span is not None
    assert span <= 100


def test_library_root_no_longer_owns_pin_table_generator() -> None:
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
    assert "lib_generate_symbol_from_pintable" not in nested_names

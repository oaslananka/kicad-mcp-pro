from __future__ import annotations

import ast
import importlib.util

from scripts import check_architecture_boundaries as boundaries

OWNED_FUNCTIONS = {
    "lib_generate_footprint_ipc7351",
    "lib_validate_footprint_ipc7351",
    "lib_certify_footprint",
}


def test_footprint_engineering_modules_are_extracted_and_tracked() -> None:
    assert importlib.util.find_spec("kicad_mcp.library.footprint_engineering") is not None
    assert importlib.util.find_spec("kicad_mcp.tools.library_footprint_engineering") is not None
    assert "kicad_mcp.library.footprint_engineering" in boundaries.DOMAIN_MODULES
    assert "kicad_mcp.library.footprint_engineering" in boundaries.PURE_HELPERS
    assert "kicad_mcp.tools.library_footprint_engineering" in boundaries.DOMAIN_MODULES


def test_footprint_engineering_adapter_does_not_import_library_monolith() -> None:
    module_name = "kicad_mcp.tools.library_footprint_engineering"
    adapter = boundaries.DOMAIN_MODULES[module_name]
    assert "kicad_mcp.tools.library" not in boundaries._imports_for(module_name, adapter)


def test_footprint_engineering_register_stays_bounded() -> None:
    module_name = "kicad_mcp.tools.library_footprint_engineering"
    span = boundaries._function_span(boundaries.DOMAIN_MODULES[module_name], "register")
    assert span is not None
    assert span <= 150
    assert boundaries.REGISTER_LINE_LIMITS[module_name] == 150


def test_library_root_no_longer_owns_footprint_engineering_tools() -> None:
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

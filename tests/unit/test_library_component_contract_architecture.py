from __future__ import annotations

import ast

from scripts import check_architecture_boundaries as boundaries


def test_architecture_checker_tracks_library_component_contract_modules() -> None:
    assert "kicad_mcp.library.component_contract" in boundaries.DOMAIN_MODULES
    assert "kicad_mcp.library.component_contract" in boundaries.PURE_HELPERS
    assert "kicad_mcp.tools.library_component_contract" in boundaries.DOMAIN_MODULES


def test_component_contract_adapter_does_not_import_library_monolith() -> None:
    module_name = "kicad_mcp.tools.library_component_contract"
    adapter = boundaries.DOMAIN_MODULES[module_name]
    assert "kicad_mcp.tools.library" not in boundaries._imports_for(module_name, adapter)


def test_component_contract_register_stays_below_reviewed_limit() -> None:
    module_name = "kicad_mcp.tools.library_component_contract"
    span = boundaries._function_span(boundaries.DOMAIN_MODULES[module_name], "register")
    assert span is not None
    assert span <= 100
    assert boundaries.REGISTER_LINE_LIMITS[module_name] == 100


def test_library_root_no_longer_owns_component_contract_tool() -> None:
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
    assert "lib_verify_component_contract" not in nested_names

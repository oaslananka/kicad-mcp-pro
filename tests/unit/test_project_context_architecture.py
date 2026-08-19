from __future__ import annotations

import ast

from scripts import check_architecture_boundaries as boundaries

OWNED_FUNCTIONS = {"kicad_set_project", "kicad_get_project_info"}


def test_architecture_checker_tracks_project_context_modules() -> None:
    assert "kicad_mcp.project.context" in boundaries.DOMAIN_MODULES
    assert "kicad_mcp.project.context" in boundaries.PURE_HELPERS
    assert "kicad_mcp.tools.project_context" in boundaries.DOMAIN_MODULES


def test_project_context_adapter_does_not_import_project_monolith() -> None:
    module_name = "kicad_mcp.tools.project_context"
    adapter = boundaries.DOMAIN_MODULES.get(module_name)
    assert adapter is not None, "Project context adapter must be tracked"
    assert "kicad_mcp.tools.project" not in boundaries._imports_for(module_name, adapter)


def test_project_context_register_stays_bounded() -> None:
    module_name = "kicad_mcp.tools.project_context"
    adapter = boundaries.DOMAIN_MODULES.get(module_name)
    assert adapter is not None, "Project context adapter must be tracked"
    span = boundaries._function_span(adapter, "register")
    assert span is not None
    assert span <= 55
    assert boundaries.REGISTER_LINE_LIMITS[module_name] == 55


def test_project_root_no_longer_owns_context_tools() -> None:
    root = boundaries.SRC_ROOT / "kicad_mcp" / "tools" / "project.py"
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

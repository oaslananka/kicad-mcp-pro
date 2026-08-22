from __future__ import annotations

import ast

from scripts import check_architecture_boundaries as boundaries

DOMAIN = "kicad_mcp.project.validation_loops"
ADAPTER = "kicad_mcp.tools.project_validation_loops"
PROJECT_ROOT = "kicad_mcp.tools.project"


def test_architecture_checker_tracks_validation_loop_modules() -> None:
    assert DOMAIN in boundaries.DOMAIN_MODULES
    assert DOMAIN in boundaries.PURE_HELPERS
    assert ADAPTER in boundaries.DOMAIN_MODULES
    assert boundaries.ADAPTER_FORBIDDEN_IMPORT_PREFIXES[ADAPTER] == (PROJECT_ROOT,)
    assert boundaries.REGISTER_LINE_LIMITS[ADAPTER] == 55


def test_validation_loop_modules_do_not_import_project_monolith() -> None:
    for module_name in (DOMAIN, ADAPTER):
        path = boundaries.DOMAIN_MODULES.get(module_name)
        assert path is not None
        assert PROJECT_ROOT not in boundaries._imports_for(module_name, path)


def test_validation_loop_adapter_register_stays_bounded() -> None:
    path = boundaries.DOMAIN_MODULES.get(ADAPTER)
    assert path is not None
    span = boundaries._function_span(path, "register")
    assert span is not None
    assert span <= 55


def test_project_root_no_longer_owns_validation_loop_tools() -> None:
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
    assert "project_auto_fix_loop" not in nested_names
    assert "project_full_validation_loop" not in nested_names

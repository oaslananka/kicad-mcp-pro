from __future__ import annotations

import ast

from scripts import check_architecture_boundaries as boundaries


def test_architecture_checker_tracks_project_workflow_modules() -> None:
    assert "kicad_mcp.project.workflow" in boundaries.DOMAIN_MODULES
    assert "kicad_mcp.project.workflow" in boundaries.PURE_HELPERS
    assert "kicad_mcp.tools.project_workflow" in boundaries.DOMAIN_MODULES
    assert boundaries.ADAPTER_FORBIDDEN_IMPORT_PREFIXES["kicad_mcp.tools.project_workflow"] == (
        "kicad_mcp.tools.project",
    )


def test_project_workflow_modules_do_not_import_project_monolith() -> None:
    for module_name in ("kicad_mcp.project.workflow", "kicad_mcp.tools.project_workflow"):
        path = boundaries.DOMAIN_MODULES.get(module_name)
        assert path is not None, f"{module_name} must be tracked"
        assert "kicad_mcp.tools.project" not in boundaries._imports_for(module_name, path)


def test_project_workflow_register_stays_bounded() -> None:
    module_name = "kicad_mcp.tools.project_workflow"
    adapter = boundaries.DOMAIN_MODULES.get(module_name)
    assert adapter is not None, "Project workflow adapter must be tracked"
    span = boundaries._function_span(adapter, "register")
    assert span is not None
    assert span <= 55
    assert boundaries.REGISTER_LINE_LIMITS[module_name] == 55


def test_project_root_no_longer_owns_workflow_tool() -> None:
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
    assert "project_design_workflow" not in nested_names

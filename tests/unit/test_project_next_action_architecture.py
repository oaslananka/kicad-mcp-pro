from __future__ import annotations

import ast

from scripts import check_architecture_boundaries as boundaries


def test_architecture_checker_tracks_next_action_modules() -> None:
    assert "kicad_mcp.project.next_action" in boundaries.DOMAIN_MODULES
    assert "kicad_mcp.project.next_action" in boundaries.PURE_HELPERS
    assert boundaries.ADAPTER_FORBIDDEN_IMPORT_PREFIXES["kicad_mcp.tools.project_next_action"] == (
        "kicad_mcp.tools.project",
    )
    assert boundaries.REGISTER_LINE_LIMITS["kicad_mcp.tools.project_next_action"] == 55


def test_next_action_modules_do_not_import_project_monolith() -> None:
    for module_name in ("kicad_mcp.project.next_action", "kicad_mcp.tools.project_next_action"):
        path = boundaries.DOMAIN_MODULES.get(module_name)
        assert path is not None
        assert "kicad_mcp.tools.project" not in boundaries._imports_for(module_name, path)


def test_project_root_no_longer_owns_next_action_tool() -> None:
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
    assert "project_get_next_action" not in nested_names


def test_board_state_resource_no_longer_imports_project_monolith_for_next_action() -> None:
    text = (boundaries.SRC_ROOT / "kicad_mcp" / "resources" / "board_state.py").read_text(
        encoding="utf-8"
    )
    next_action_block = text.split('@mcp.resource("kicad://project/next_action")', 1)[1].split(
        "@mcp.resource(", 1
    )[0]
    assert "tools.project import _next_action_payload" not in next_action_block
    assert "project.next_action" in next_action_block

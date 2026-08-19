import ast

from scripts import check_architecture_boundaries as boundaries


def test_project_discovery_modules_are_tracked() -> None:
    assert "kicad_mcp.project.discovery" in boundaries.DOMAIN_MODULES
    assert "kicad_mcp.project.discovery" in boundaries.PURE_HELPERS
    assert "kicad_mcp.tools.project_discovery" in boundaries.DOMAIN_MODULES


def test_project_root_no_longer_owns_discovery_tools() -> None:
    root = boundaries.SRC_ROOT / "kicad_mcp" / "tools" / "project.py"
    tree = ast.parse(root.read_text(encoding="utf-8"))
    register_node = next(
        n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "register"
    )
    nested = {
        n.name for n in register_node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert {"kicad_list_recent_projects", "kicad_scan_directory"}.isdisjoint(nested)

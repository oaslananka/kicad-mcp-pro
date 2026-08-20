from __future__ import annotations

import ast
import importlib.util
from pathlib import Path


def test_project_creation_modules_exist_and_root_no_longer_owns_tool() -> None:
    assert importlib.util.find_spec("kicad_mcp.project.creation") is not None
    assert importlib.util.find_spec("kicad_mcp.tools.project_creation") is not None

    project_path = Path("src/kicad_mcp/tools/project.py")
    tree = ast.parse(project_path.read_text(encoding="utf-8"))
    register = next(
        node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "register"
    )
    nested_names = {node.name for node in ast.walk(register) if isinstance(node, ast.FunctionDef)}
    assert "kicad_create_new_project" not in nested_names

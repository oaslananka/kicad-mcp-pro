"""Architecture guards for validation policy state extraction."""

from __future__ import annotations

import ast
from pathlib import Path


def test_policy_service_does_not_import_fastmcp_or_validation_monolith() -> None:
    path = Path("src/kicad_mcp/validation/policy_state.py")
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    assert not any(name.startswith("mcp") for name in imports)
    assert "kicad_mcp.tools.validation" not in imports

"""Reusable AST assertions for repository architecture tests (no production imports)."""

from __future__ import annotations

import ast
from pathlib import Path


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.add(node.module or "")
    return imports


def _function_span(path: Path, name: str) -> int:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    matches = [
        node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == name
    ]
    assert len(matches) == 1
    node = matches[0]
    assert node.end_lineno is not None
    return node.end_lineno - node.lineno + 1

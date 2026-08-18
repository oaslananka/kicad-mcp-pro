"""Architecture guards for generated-file format migration."""

from __future__ import annotations

import ast
from pathlib import Path

MODULE = Path("src/kicad_mcp/file_formats.py")
MAX_DISPATCH_LINES = 35


def _top_level_functions() -> dict[str, ast.FunctionDef]:
    tree = ast.parse(MODULE.read_text(encoding="utf-8"), filename=str(MODULE))
    return {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}


def _span(node: ast.FunctionDef) -> int:
    assert node.end_lineno is not None
    return node.end_lineno - node.lineno + 1


def test_generated_format_upgrade_dispatch_stays_bounded() -> None:
    functions = _top_level_functions()
    assert _span(functions["upgrade_generated_file"]) <= MAX_DISPATCH_LINES

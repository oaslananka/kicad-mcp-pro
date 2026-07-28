"""Architecture guards for the bounded validation composition root."""

from __future__ import annotations

import ast
from pathlib import Path

VALIDATION_MODULE = Path("src/kicad_mcp/tools/validation.py")
MAX_REGISTER_LINES = 300
EXPECTED_HELPERS = {
    "_register_drc_rule_tools",
    "_register_validation_gate_tools",
    "_register_targeted_validation_tools",
}


def _top_level_functions() -> dict[str, ast.FunctionDef]:
    tree = ast.parse(VALIDATION_MODULE.read_text(encoding="utf-8"))
    return {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}


def _span(node: ast.FunctionDef) -> int:
    assert node.end_lineno is not None
    return node.end_lineno - node.lineno + 1


def test_validation_register_and_helpers_stay_bounded() -> None:
    functions = _top_level_functions()
    assert EXPECTED_HELPERS <= functions.keys()
    assert _span(functions["register"]) <= MAX_REGISTER_LINES
    for name in EXPECTED_HELPERS:
        assert _span(functions[name]) <= MAX_REGISTER_LINES, name


def test_validation_register_contains_no_nested_tool_definitions() -> None:
    register = _top_level_functions()["register"]
    nested = [
        node.name
        for node in register.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    assert nested == []

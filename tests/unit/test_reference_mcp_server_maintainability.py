from __future__ import annotations

import ast
from pathlib import Path

SOURCE = Path(__file__).parents[2] / "src/kicad_mcp/evals/reference_mcp_server.py"


def _function(name: str) -> ast.FunctionDef:
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"missing function {name}")


def _control_flow_count(function: ast.FunctionDef) -> int:
    control_flow = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.Try, ast.IfExp)
    return sum(isinstance(node, control_flow) for node in ast.walk(function))


def _nested_if_expression_lines(function: ast.FunctionDef) -> list[int]:
    nested: list[int] = []
    for node in ast.walk(function):
        if not isinstance(node, ast.IfExp):
            continue
        if isinstance(node.body, ast.IfExp) or isinstance(node.orelse, ast.IfExp):
            nested.append(node.lineno)
    return nested


def test_timestamp_normalization_has_no_nested_conditional_expression() -> None:
    function = _function("_normalize_kicad_timestamp_bytes")

    assert _nested_if_expression_lines(function) == []


def test_bom_canonicalizer_keeps_orchestration_control_flow_bounded() -> None:
    function = _function("_canonicalize_snapshot_bom")

    assert _control_flow_count(function) <= 5


def _module_assignment_names() -> set[str]:
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Assign):
            names.update(target.id for target in node.targets if isinstance(target, ast.Name))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
    return names


def test_gerber_timestamp_matching_avoids_backtracking_regex_constants() -> None:
    risky_constants = {"_GERBER_CREATED_BY_RE", "_DRILL_CREATED_BY_RE"}

    assert risky_constants.isdisjoint(_module_assignment_names())


def test_created_by_date_separator_is_defined_once() -> None:
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    occurrences = sum(
        isinstance(node, ast.Constant) and node.value == b" date " for node in ast.walk(tree)
    )

    assert occurrences == 1

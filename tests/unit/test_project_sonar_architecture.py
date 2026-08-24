from __future__ import annotations

import ast
from pathlib import Path

PROJECT_DIR = Path("src/kicad_mcp/project")


def _class_method_span(path: Path, class_name: str, method_name: str) -> int:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    class_node = next(
        node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == class_name
    )
    method = next(
        node
        for node in class_node.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == method_name
    )
    assert method.end_lineno is not None
    return method.end_lineno - method.lineno + 1


def _string_literal_count(path: Path, literal: str) -> int:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return sum(
        1
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value == literal
    )


def test_validation_loop_composition_methods_stay_reviewably_small() -> None:
    path = PROJECT_DIR / "validation_loops.py"

    assert _class_method_span(path, "ProjectValidationLoopService", "auto_fix_loop") <= 80
    assert _class_method_span(path, "ProjectValidationLoopService", "full_validation_loop") <= 70


def test_next_action_heading_has_one_literal_source() -> None:
    assert _string_literal_count(PROJECT_DIR / "next_action.py", "Project next action:") == 1


def test_edit_impact_casts_do_not_duplicate_type_literal() -> None:
    assert _string_literal_count(PROJECT_DIR / "edit_impact.py", "dict[str, Any]") == 0

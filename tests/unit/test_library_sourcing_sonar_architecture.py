from __future__ import annotations

import ast
from pathlib import Path

MODULE = Path("src/kicad_mcp/library/sourcing.py")


def _service_method(name: str) -> ast.FunctionDef:
    tree = ast.parse(MODULE.read_text(encoding="utf-8"), filename=str(MODULE))
    service = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "LibrarySourcingService"
    )
    return next(
        node for node in service.body if isinstance(node, ast.FunctionDef) and node.name == name
    )


def _span(name: str) -> int:
    method = _service_method(name)
    assert method.end_lineno is not None
    return method.end_lineno - method.lineno + 1


def test_sourcing_composition_methods_stay_reviewably_small() -> None:
    assert _span("search_components") <= 75
    assert _span("check_sourcing_policy") <= 75
    assert _span("get_bom_with_pricing") <= 35
    assert _span("check_stock_availability") <= 45


def test_not_available_text_has_one_literal_source() -> None:
    tree = ast.parse(MODULE.read_text(encoding="utf-8"), filename=str(MODULE))
    count = sum(isinstance(node, ast.Constant) and node.value == "(n/a)" for node in ast.walk(tree))
    assert count == 1


def test_sourcing_policy_has_no_nested_conditional_expression() -> None:
    method = _service_method("check_sourcing_policy")
    nested = [
        node
        for node in ast.walk(method)
        if isinstance(node, ast.IfExp)
        and (isinstance(node.body, ast.IfExp) or isinstance(node.orelse, ast.IfExp))
    ]
    assert nested == []


def test_oserror_handlers_do_not_repeat_filenotfounderror() -> None:
    tree = ast.parse(MODULE.read_text(encoding="utf-8"), filename=str(MODULE))
    redundant: list[int] = []
    for handler in (node for node in ast.walk(tree) if isinstance(node, ast.ExceptHandler)):
        if not isinstance(handler.type, ast.Tuple):
            continue
        names = {node.id for node in ast.walk(handler.type) if isinstance(node, ast.Name)}
        if {"OSError", "FileNotFoundError"} <= names:
            redundant.append(handler.lineno)
    assert redundant == []

from __future__ import annotations

import ast
from pathlib import Path

from scripts import check_architecture_boundaries as boundaries


def assert_service_adapter_tracked(service: str, adapter: str, root: str) -> None:
    assert service in boundaries.DOMAIN_MODULES
    assert service in boundaries.PURE_HELPERS
    assert adapter in boundaries.DOMAIN_MODULES
    assert root in boundaries.DOMAIN_MODULES


def assert_adapter_boundary(adapter: str, root: str, *, line_limit: int) -> None:
    path = boundaries.DOMAIN_MODULES[adapter]
    assert root not in boundaries._imports_for(adapter, path)
    assert boundaries.ADAPTER_FORBIDDEN_IMPORT_PREFIXES[adapter] == (root,)
    span = boundaries._function_span(path, "register")
    assert span is not None
    assert span <= line_limit
    assert boundaries.REGISTER_LINE_LIMITS[adapter] == line_limit


def root_register_contract(root: str) -> tuple[str, list[str], int]:
    path: Path = boundaries.DOMAIN_MODULES[root]
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    register_node = next(
        node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "register"
    )
    nested = [
        node.name
        for node in register_node.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    span = boundaries._function_span(path, "register")
    assert span is not None
    return path.read_text(encoding="utf-8"), nested, span

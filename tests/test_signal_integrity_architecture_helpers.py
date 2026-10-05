from __future__ import annotations

import ast
from pathlib import Path

from scripts import check_architecture_boundaries as boundaries


def tracked_module_state(service: str, adapter: str, root: str) -> tuple[bool, bool, bool, bool]:
    """Return architecture-registry membership facts for one extracted SI tool."""
    return (
        service in boundaries.DOMAIN_MODULES,
        service in boundaries.PURE_HELPERS,
        adapter in boundaries.DOMAIN_MODULES,
        root in boundaries.DOMAIN_MODULES,
    )


def adapter_boundary_state(
    adapter: str,
) -> tuple[set[str], tuple[str, ...], int | None, int | None]:
    """Return import and register-limit facts for a thin SI adapter."""
    path = boundaries.DOMAIN_MODULES[adapter]
    return (
        boundaries._imports_for(adapter, path),
        boundaries.ADAPTER_FORBIDDEN_IMPORT_PREFIXES[adapter],
        boundaries._function_span(path, "register"),
        boundaries.REGISTER_LINE_LIMITS.get(adapter),
    )


def root_register_contract(root: str) -> tuple[str, list[str], int | None]:
    """Return the source, nested tools, and register span for an SI composition root."""
    path: Path = boundaries.DOMAIN_MODULES[root]
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    register_node = next(
        node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "register"
    )
    nested = [
        node.name
        for node in register_node.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    return source, nested, boundaries._function_span(path, "register")

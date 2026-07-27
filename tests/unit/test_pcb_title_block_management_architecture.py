from __future__ import annotations

import ast
from pathlib import Path

from scripts import check_architecture_boundaries as boundaries


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


def test_architecture_checker_tracks_pcb_title_block_modules() -> None:
    assert "kicad_mcp.pcb.title_block_management" in boundaries.DOMAIN_MODULES
    assert "kicad_mcp.pcb.title_block_management" in boundaries.PURE_HELPERS
    assert "kicad_mcp.tools.pcb_title_block_management" in boundaries.DOMAIN_MODULES


def test_pcb_title_block_adapter_does_not_import_monolith() -> None:
    adapter = boundaries.SRC_ROOT / "kicad_mcp" / "tools" / "pcb_title_block_management.py"
    assert "kicad_mcp.tools.pcb" not in _imports(adapter)


def test_pcb_title_block_register_stays_below_300_lines() -> None:
    adapter = boundaries.SRC_ROOT / "kicad_mcp" / "tools" / "pcb_title_block_management.py"
    assert _function_span(adapter, "register") <= 300
    assert boundaries.REGISTER_LINE_LIMITS["kicad_mcp.tools.pcb_title_block_management"] == 300


def test_pcb_composition_root_no_longer_owns_title_block_tool() -> None:
    root = boundaries.SRC_ROOT / "kicad_mcp" / "tools" / "pcb.py"
    tree = ast.parse(root.read_text(encoding="utf-8"), filename=str(root))
    register = next(
        node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "register"
    )
    nested = {
        node.name
        for node in register.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert "pcb_set_title_block_info" not in nested

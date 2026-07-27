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
    node = next(
        item for item in tree.body if isinstance(item, ast.FunctionDef) and item.name == name
    )
    assert node.end_lineno is not None
    return node.end_lineno - node.lineno + 1


def test_architecture_checker_tracks_pcb_board_inspection_modules() -> None:
    assert "kicad_mcp.pcb.board_inspection" in boundaries.DOMAIN_MODULES
    assert "kicad_mcp.pcb.board_inspection" in boundaries.PURE_HELPERS
    assert "kicad_mcp.tools.pcb_board_inspection" in boundaries.DOMAIN_MODULES


def test_pcb_board_adapter_does_not_import_monolith() -> None:
    adapter = boundaries.SRC_ROOT / "kicad_mcp" / "tools" / "pcb_board_inspection.py"
    assert "kicad_mcp.tools.pcb" not in _imports(adapter)


def test_pcb_board_register_stays_below_300_lines() -> None:
    adapter = boundaries.SRC_ROOT / "kicad_mcp" / "tools" / "pcb_board_inspection.py"
    assert _function_span(adapter, "register") <= 300
    assert boundaries.REGISTER_LINE_LIMITS["kicad_mcp.tools.pcb_board_inspection"] == 300


def test_pcb_composition_root_no_longer_owns_board_inspection_tools() -> None:
    root = boundaries.SRC_ROOT / "kicad_mcp" / "tools" / "pcb.py"
    tree = ast.parse(root.read_text(encoding="utf-8"), filename=str(root))
    register = next(
        item for item in tree.body if isinstance(item, ast.FunctionDef) and item.name == "register"
    )
    nested = {
        item.name
        for item in register.body
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert nested.isdisjoint(
        {
            "pcb_get_board_summary",
            "pcb_get_tracks",
            "pcb_get_vias",
            "pcb_get_footprints",
        }
    )

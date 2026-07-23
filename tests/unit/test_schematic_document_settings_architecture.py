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


def test_architecture_checker_tracks_document_settings_modules() -> None:
    assert "kicad_mcp.schematic.document_settings" in boundaries.DOMAIN_MODULES
    assert "kicad_mcp.schematic.document_settings" in boundaries.PURE_HELPERS
    assert "kicad_mcp.tools.schematic_document_settings" in boundaries.DOMAIN_MODULES


def test_document_settings_adapter_does_not_import_monolith() -> None:
    adapter = boundaries.SRC_ROOT / "kicad_mcp" / "tools" / "schematic_document_settings.py"
    assert "kicad_mcp.tools.schematic" not in _imports(adapter)
    assert boundaries.ADAPTER_FORBIDDEN_IMPORT_PREFIXES[
        "kicad_mcp.tools.schematic_document_settings"
    ] == ("kicad_mcp.tools.schematic",)


def test_document_settings_register_stays_below_300_lines() -> None:
    adapter = boundaries.SRC_ROOT / "kicad_mcp" / "tools" / "schematic_document_settings.py"
    assert _function_span(adapter, "register") <= 300
    assert boundaries.REGISTER_LINE_LIMITS["kicad_mcp.tools.schematic_document_settings"] == 300

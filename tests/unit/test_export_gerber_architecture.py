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


def test_architecture_checker_tracks_export_gerber_modules() -> None:
    assert "kicad_mcp.export.gerber" in boundaries.DOMAIN_MODULES
    assert "kicad_mcp.export.gerber" in boundaries.PURE_HELPERS
    assert "kicad_mcp.tools.export_gerber" in boundaries.DOMAIN_MODULES


def test_export_gerber_adapter_does_not_import_monolith() -> None:
    adapter = boundaries.SRC_ROOT / "kicad_mcp" / "tools" / "export_gerber.py"
    assert adapter.exists()
    assert "kicad_mcp.tools.export" not in _imports(adapter)


def test_export_gerber_register_stays_below_100_lines() -> None:
    adapter = boundaries.SRC_ROOT / "kicad_mcp" / "tools" / "export_gerber.py"
    assert adapter.exists()
    assert _function_span(adapter, "register") <= 100
    assert boundaries.REGISTER_LINE_LIMITS["kicad_mcp.tools.export_gerber"] == 100


def test_export_composition_root_no_longer_owns_gerber_tools() -> None:
    root = boundaries.SRC_ROOT / "kicad_mcp" / "tools" / "export.py"
    tree = ast.parse(root.read_text(encoding="utf-8"), filename=str(root))
    register_node = next(
        node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "register"
    )
    nested = {
        node.name
        for node in register_node.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert nested.isdisjoint({"_export_gerber", "export_gerber"})


def test_manufacturing_package_uses_shared_gerber_service() -> None:
    root = boundaries.SRC_ROOT / "kicad_mcp" / "tools" / "export.py"
    tree = ast.parse(root.read_text(encoding="utf-8"), filename=str(root))
    register_node = next(
        node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "register"
    )
    manufacturing = next(
        node
        for node in register_node.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "export_manufacturing_package"
    )
    calls = [node for node in ast.walk(manufacturing) if isinstance(node, ast.Call)]
    assert any(
        isinstance(call.func, ast.Attribute)
        and isinstance(call.func.value, ast.Name)
        and call.func.value.id == "gerber_service"
        and call.func.attr == "export"
        for call in calls
    )

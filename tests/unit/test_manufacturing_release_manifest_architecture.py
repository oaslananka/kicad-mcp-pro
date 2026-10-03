from __future__ import annotations

import ast

from scripts import check_architecture_boundaries as boundaries


def test_architecture_checker_tracks_release_manifest_modules() -> None:
    assert "kicad_mcp.manufacturing.release_manifest" in boundaries.DOMAIN_MODULES
    assert "kicad_mcp.manufacturing.release_manifest" in boundaries.PURE_HELPERS
    assert "kicad_mcp.tools.manufacturing_release_manifest" in boundaries.DOMAIN_MODULES


def test_release_manifest_adapter_stays_thin_and_off_root_monolith() -> None:
    module_name = "kicad_mcp.tools.manufacturing_release_manifest"
    path = boundaries.DOMAIN_MODULES[module_name]
    imports = boundaries._imports_for(module_name, path)
    assert boundaries._MANUFACTURING_ROOT_MODULE not in imports
    span = boundaries._function_span(path, "register")
    assert span is not None
    assert span <= 75
    assert boundaries.REGISTER_LINE_LIMITS[module_name] == 75


def test_manufacturing_root_delegates_release_manifest_and_shrinks() -> None:
    root = boundaries.SRC_ROOT / "kicad_mcp" / "tools" / "manufacturing.py"
    tree = ast.parse(root.read_text(encoding="utf-8"), filename=str(root))
    register_node = next(
        node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "register"
    )
    nested = {
        node.name
        for node in register_node.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }

    assert "mfg_generate_release_manifest" not in nested
    span = boundaries._function_span(root, "register")
    assert span is not None
    assert span <= 305

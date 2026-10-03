from __future__ import annotations

import ast

from scripts import check_architecture_boundaries as boundaries


def test_architecture_checker_tracks_panelization_service_and_adapter() -> None:
    assert "kicad_mcp.manufacturing.panelization" in boundaries.DOMAIN_MODULES
    assert "kicad_mcp.manufacturing.panelization" in boundaries.PURE_HELPERS
    assert "kicad_mcp.tools.manufacturing_panelization" in boundaries.DOMAIN_MODULES


def test_panelization_adapter_is_thin_and_cannot_back_import_monolith() -> None:
    module_name = "kicad_mcp.tools.manufacturing_panelization"
    adapter = boundaries.DOMAIN_MODULES[module_name]
    assert boundaries._MANUFACTURING_ROOT_MODULE not in boundaries._imports_for(
        module_name, adapter
    )
    span = boundaries._function_span(adapter, "register")
    assert span is not None
    assert span <= 95
    assert boundaries.REGISTER_LINE_LIMITS[module_name] == 95


def test_manufacturing_root_delegates_panelization_and_shrinks() -> None:
    root = boundaries.DOMAIN_MODULES[boundaries._MANUFACTURING_ROOT_MODULE]
    tree = ast.parse(root.read_text(encoding="utf-8"), filename=str(root))
    register_node = next(
        node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "register"
    )
    nested = {
        node.name
        for node in register_node.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert "mfg_panelize" not in nested
    span = boundaries._function_span(root, "register")
    assert span is not None
    assert span <= 270

from __future__ import annotations

import ast

from scripts import check_architecture_boundaries as boundaries


def test_architecture_checker_tracks_release_evidence_modules() -> None:
    assert "kicad_mcp.manufacturing.release_evidence" in boundaries.DOMAIN_MODULES
    assert "kicad_mcp.manufacturing.release_evidence" in boundaries.PURE_HELPERS
    assert "kicad_mcp.tools.manufacturing_release_evidence" in boundaries.DOMAIN_MODULES


def test_release_evidence_adapter_is_thin_and_cannot_import_manufacturing_root() -> None:
    module_name = "kicad_mcp.tools.manufacturing_release_evidence"
    adapter = boundaries.DOMAIN_MODULES[module_name]
    assert "kicad_mcp.tools.manufacturing" not in boundaries._imports_for(module_name, adapter)
    span = boundaries._function_span(adapter, "register")
    assert span is not None
    assert span <= 100
    assert boundaries.REGISTER_LINE_LIMITS[module_name] == 100


def test_manufacturing_root_delegates_release_evidence_and_shrinks_again() -> None:
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

    assert "mfg_create_release_evidence" not in nested
    span = boundaries._function_span(root, "register")
    assert span is not None
    assert span <= 575

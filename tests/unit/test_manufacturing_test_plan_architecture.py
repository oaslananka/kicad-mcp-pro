from __future__ import annotations

import ast

from scripts import check_architecture_boundaries as boundaries


def test_architecture_checker_tracks_test_plan_service_and_adapter() -> None:
    assert "kicad_mcp.manufacturing.test_plan" in boundaries.DOMAIN_MODULES
    assert "kicad_mcp.manufacturing.test_plan" in boundaries.PURE_HELPERS
    assert "kicad_mcp.tools.manufacturing_test_plan" in boundaries.DOMAIN_MODULES


def test_test_plan_adapter_stays_thin_and_away_from_root_monolith() -> None:
    module_name = "kicad_mcp.tools.manufacturing_test_plan"
    adapter = boundaries.DOMAIN_MODULES[module_name]
    assert "kicad_mcp.tools.manufacturing" not in boundaries._imports_for(module_name, adapter)
    span = boundaries._function_span(adapter, "register")
    assert span is not None
    assert span <= 80
    assert boundaries.REGISTER_LINE_LIMITS[module_name] == 80


def test_manufacturing_root_delegates_test_plan_and_shrinks_again() -> None:
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

    assert "mfg_generate_test_plan" not in nested
    span = boundaries._function_span(root, "register")
    assert span is not None
    assert span <= 415

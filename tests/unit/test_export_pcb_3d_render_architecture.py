from __future__ import annotations

import ast

from scripts import check_architecture_boundaries as boundaries


def test_architecture_checker_tracks_export_pcb_3d_render_modules() -> None:
    assert "kicad_mcp.export.pcb_3d_render" in boundaries.DOMAIN_MODULES
    assert "kicad_mcp.export.pcb_3d_render" in boundaries.PURE_HELPERS
    assert "kicad_mcp.tools.export_pcb_3d_render" in boundaries.DOMAIN_MODULES


def test_export_pcb_3d_render_adapter_does_not_import_monolith() -> None:
    module_name = "kicad_mcp.tools.export_pcb_3d_render"
    adapter = boundaries.DOMAIN_MODULES[module_name]
    assert "kicad_mcp.tools.export" not in boundaries._imports_for(module_name, adapter)


def test_export_pcb_3d_render_register_stays_below_reviewed_limit() -> None:
    module_name = "kicad_mcp.tools.export_pcb_3d_render"
    span = boundaries._function_span(boundaries.DOMAIN_MODULES[module_name], "register")
    assert span is not None
    assert span <= 140
    assert boundaries.REGISTER_LINE_LIMITS[module_name] == 140


def test_export_composition_root_no_longer_owns_pcb_3d_render_tools() -> None:
    root = boundaries.SRC_ROOT / "kicad_mcp" / "tools" / "export.py"
    tree = ast.parse(root.read_text(encoding="utf-8"), filename=str(root))
    register_node = next(
        node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "register"
    )
    nested_names = {
        node.name
        for node in register_node.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert nested_names.isdisjoint({"_export_3d_render", "export_3d_render"})

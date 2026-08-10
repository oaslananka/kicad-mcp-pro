from __future__ import annotations

import ast

from scripts import check_architecture_boundaries as boundaries

OWNED_FUNCTIONS = {
    "_export_3d_model",
    "pcb_export_brep",
    "export_brep",
    "pcb_export_glb",
    "export_glb",
    "pcb_export_gencad",
    "export_gencad",
    "pcb_export_ipcd356",
    "export_ipc_d356",
    "pcb_export_ply",
    "export_ply",
    "pcb_export_stl",
    "export_stl",
    "pcb_export_u3d",
    "export_u3d",
    "pcb_export_vrml",
    "export_vrml",
    "pcb_export_ps",
    "export_ps",
    "export_3d_step",
    "export_step",
    "export_stepz",
    "export_xao",
}


def test_architecture_checker_tracks_export_pcb_file_format_modules() -> None:
    assert "kicad_mcp.export.pcb_file_formats" in boundaries.DOMAIN_MODULES
    assert "kicad_mcp.export.pcb_file_formats" in boundaries.PURE_HELPERS
    assert "kicad_mcp.tools.export_pcb_file_formats" in boundaries.DOMAIN_MODULES


def test_export_pcb_file_format_adapter_does_not_import_monolith() -> None:
    module_name = "kicad_mcp.tools.export_pcb_file_formats"
    adapter = boundaries.DOMAIN_MODULES[module_name]
    assert "kicad_mcp.tools.export" not in boundaries._imports_for(module_name, adapter)


def test_export_pcb_file_format_register_stays_below_100_lines() -> None:
    module_name = "kicad_mcp.tools.export_pcb_file_formats"
    span = boundaries._function_span(boundaries.DOMAIN_MODULES[module_name], "register")
    assert span is not None
    assert span <= 100
    assert boundaries.REGISTER_LINE_LIMITS[module_name] == 100


def test_export_composition_root_no_longer_owns_single_file_format_family() -> None:
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
    assert nested_names.isdisjoint(OWNED_FUNCTIONS)

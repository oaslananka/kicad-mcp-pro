from __future__ import annotations

import ast

from scripts import check_architecture_boundaries as boundaries

OWNED_FUNCTIONS = {
    "_export_pick_and_place",
    "export_pick_and_place",
    "_export_ipc2581",
    "export_ipc2581",
    "_export_odb",
    "export_odb",
}


def test_architecture_checker_tracks_export_pcb_manufacturing_output_modules() -> None:
    assert "kicad_mcp.export.pcb_manufacturing_outputs" in boundaries.DOMAIN_MODULES
    assert "kicad_mcp.export.pcb_manufacturing_outputs" in boundaries.PURE_HELPERS
    assert "kicad_mcp.tools.export_pcb_manufacturing_outputs" in boundaries.DOMAIN_MODULES


def test_export_pcb_manufacturing_output_adapter_does_not_import_monolith() -> None:
    module_name = "kicad_mcp.tools.export_pcb_manufacturing_outputs"
    adapter = boundaries.DOMAIN_MODULES[module_name]
    assert "kicad_mcp.tools.export" not in boundaries._imports_for(module_name, adapter)


def test_export_pcb_manufacturing_output_register_stays_below_100_lines() -> None:
    module_name = "kicad_mcp.tools.export_pcb_manufacturing_outputs"
    span = boundaries._function_span(boundaries.DOMAIN_MODULES[module_name], "register")
    assert span is not None
    assert span <= 100
    assert boundaries.REGISTER_LINE_LIMITS[module_name] == 100


def test_export_composition_root_moves_only_low_level_manufacturing_outputs() -> None:
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
    assert nested_names.isdisjoint(OWNED_FUNCTIONS | {"export_manufacturing_package"})

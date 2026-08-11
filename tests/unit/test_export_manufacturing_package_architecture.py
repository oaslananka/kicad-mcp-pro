from __future__ import annotations

import ast

from scripts import check_architecture_boundaries as boundaries

MANUFACTURING_HELPERS = {
    "_release_evidence_error",
    "_load_release_evidence",
    "_file_sha256",
    "_manufacturing_artifacts",
    "_write_handoff_report",
}


def test_architecture_checker_tracks_manufacturing_package_modules() -> None:
    assert "kicad_mcp.export.manufacturing_package" in boundaries.DOMAIN_MODULES
    assert "kicad_mcp.export.manufacturing_package" in boundaries.PURE_HELPERS
    assert "kicad_mcp.tools.export_manufacturing_package" in boundaries.DOMAIN_MODULES


def test_manufacturing_package_adapter_does_not_import_export_monolith() -> None:
    module_name = "kicad_mcp.tools.export_manufacturing_package"
    adapter = boundaries.DOMAIN_MODULES[module_name]
    assert "kicad_mcp.tools.export" not in boundaries._imports_for(module_name, adapter)


def test_manufacturing_package_register_stays_below_100_lines() -> None:
    module_name = "kicad_mcp.tools.export_manufacturing_package"
    span = boundaries._function_span(boundaries.DOMAIN_MODULES[module_name], "register")
    assert span is not None
    assert span <= 100
    assert boundaries.REGISTER_LINE_LIMITS[module_name] == 100


def test_export_root_no_longer_owns_manufacturing_package_or_private_release_helpers() -> None:
    root = boundaries.SRC_ROOT / "kicad_mcp" / "tools" / "export.py"
    tree = ast.parse(root.read_text(encoding="utf-8"), filename=str(root))
    top_level = {
        node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    register_node = next(
        node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "register"
    )
    nested = {
        node.name
        for node in register_node.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }

    assert MANUFACTURING_HELPERS.isdisjoint(top_level)
    assert "export_manufacturing_package" not in nested
    assert "_report_progress" in top_level

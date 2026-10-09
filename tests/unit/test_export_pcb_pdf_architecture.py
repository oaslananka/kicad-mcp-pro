from __future__ import annotations

import ast

from scripts import check_architecture_boundaries as boundaries
from tests.architecture_source_helpers import _function_span, _imports


def test_architecture_checker_tracks_export_pcb_pdf_modules() -> None:
    assert "kicad_mcp.export.pcb_pdf" in boundaries.DOMAIN_MODULES
    assert "kicad_mcp.export.pcb_pdf" in boundaries.PURE_HELPERS
    assert "kicad_mcp.tools.export_pcb_pdf" in boundaries.DOMAIN_MODULES


def test_export_pcb_pdf_adapter_does_not_import_monolith() -> None:
    adapter = boundaries.SRC_ROOT / "kicad_mcp" / "tools" / "export_pcb_pdf.py"
    assert adapter.exists()
    assert "kicad_mcp.tools.export" not in _imports(adapter)


def test_export_pcb_pdf_register_stays_below_100_lines() -> None:
    adapter = boundaries.SRC_ROOT / "kicad_mcp" / "tools" / "export_pcb_pdf.py"
    assert adapter.exists()
    assert _function_span(adapter, "register") <= 100
    assert boundaries.REGISTER_LINE_LIMITS["kicad_mcp.tools.export_pcb_pdf"] == 100


def test_export_composition_root_no_longer_owns_pcb_pdf_tools() -> None:
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
    assert nested.isdisjoint({"_export_pcb_pdf", "export_pcb_pdf"})

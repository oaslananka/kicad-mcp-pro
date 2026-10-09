from __future__ import annotations

import ast

from scripts import check_architecture_boundaries as boundaries
from tests.architecture_source_helpers import _function_span, _imports


def test_architecture_checker_tracks_pcb_session_modules() -> None:
    assert "kicad_mcp.pcb.session_inspection" in boundaries.DOMAIN_MODULES
    assert "kicad_mcp.pcb.session_inspection" in boundaries.PURE_HELPERS
    assert "kicad_mcp.tools.pcb_session_inspection" in boundaries.DOMAIN_MODULES


def test_pcb_session_adapter_does_not_import_monolith() -> None:
    adapter = boundaries.SRC_ROOT / "kicad_mcp" / "tools" / "pcb_session_inspection.py"
    assert "kicad_mcp.tools.pcb" not in _imports(adapter)


def test_pcb_session_register_stays_below_300_lines() -> None:
    adapter = boundaries.SRC_ROOT / "kicad_mcp" / "tools" / "pcb_session_inspection.py"
    assert _function_span(adapter, "register") <= 300
    assert boundaries.REGISTER_LINE_LIMITS["kicad_mcp.tools.pcb_session_inspection"] == 300


def test_pcb_composition_root_no_longer_owns_session_tools() -> None:
    root = boundaries.SRC_ROOT / "kicad_mcp" / "tools" / "pcb.py"
    tree = ast.parse(root.read_text(encoding="utf-8"), filename=str(root))
    register = next(
        item for item in tree.body if isinstance(item, ast.FunctionDef) and item.name == "register"
    )
    nested = {
        item.name
        for item in register.body
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert nested.isdisjoint({"pcb_get_selection", "pcb_get_board_as_string"})

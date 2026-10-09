from __future__ import annotations

import ast

from scripts import check_architecture_boundaries as boundaries
from tests.architecture_source_helpers import _function_span, _imports


def test_architecture_checker_tracks_pcb_origin_modules() -> None:
    assert "kicad_mcp.pcb.origin_management" in boundaries.DOMAIN_MODULES
    assert "kicad_mcp.pcb.origin_management" in boundaries.PURE_HELPERS
    assert "kicad_mcp.tools.pcb_origin_management" in boundaries.DOMAIN_MODULES


def test_pcb_origin_adapter_does_not_import_monolith() -> None:
    adapter = boundaries.SRC_ROOT / "kicad_mcp" / "tools" / "pcb_origin_management.py"
    assert "kicad_mcp.tools.pcb" not in _imports(adapter)


def test_pcb_origin_register_stays_below_300_lines() -> None:
    adapter = boundaries.SRC_ROOT / "kicad_mcp" / "tools" / "pcb_origin_management.py"
    assert _function_span(adapter, "register") <= 300
    assert boundaries.REGISTER_LINE_LIMITS["kicad_mcp.tools.pcb_origin_management"] == 300


def test_pcb_composition_root_no_longer_owns_origin_tools() -> None:
    root = boundaries.SRC_ROOT / "kicad_mcp" / "tools" / "pcb.py"
    tree = ast.parse(root.read_text(encoding="utf-8"), filename=str(root))
    register = next(
        node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "register"
    )
    nested = {
        node.name
        for node in register.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert nested.isdisjoint({"pcb_set_origin", "pcb_get_origin"})

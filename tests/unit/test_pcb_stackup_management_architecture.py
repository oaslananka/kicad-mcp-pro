from __future__ import annotations

import ast

from scripts import check_architecture_boundaries as boundaries
from tests.architecture_source_helpers import _function_span, _imports


def test_architecture_checker_tracks_pcb_stackup_modules() -> None:
    assert "kicad_mcp.pcb.stackup_management" in boundaries.DOMAIN_MODULES
    assert "kicad_mcp.pcb.stackup_management" in boundaries.PURE_HELPERS
    assert "kicad_mcp.tools.pcb_stackup_management" in boundaries.DOMAIN_MODULES


def test_pcb_stackup_adapter_does_not_import_monolith() -> None:
    adapter = boundaries.SRC_ROOT / "kicad_mcp" / "tools" / "pcb_stackup_management.py"
    assert "kicad_mcp.tools.pcb" not in _imports(adapter)


def test_pcb_stackup_register_stays_below_300_lines() -> None:
    adapter = boundaries.SRC_ROOT / "kicad_mcp" / "tools" / "pcb_stackup_management.py"
    assert _function_span(adapter, "register") <= 300
    assert boundaries.REGISTER_LINE_LIMITS["kicad_mcp.tools.pcb_stackup_management"] == 300


def test_pcb_composition_root_no_longer_owns_stackup_tools() -> None:
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
    assert nested.isdisjoint({"pcb_get_stackup", "pcb_set_stackup"})

from __future__ import annotations

import ast
from pathlib import Path

from scripts import check_architecture_boundaries as boundaries


def test_architecture_checker_tracks_release_evidence_service_and_adapter() -> None:
    assert "kicad_mcp.manufacturing.release_evidence" in boundaries.DOMAIN_MODULES
    assert "kicad_mcp.manufacturing.release_evidence" in boundaries.PURE_HELPERS
    assert "kicad_mcp.tools.manufacturing_release_evidence" in boundaries.DOMAIN_MODULES


def test_release_evidence_adapter_stays_thin_and_away_from_root_monolith() -> None:
    module_name = "kicad_mcp.tools.manufacturing_release_evidence"
    adapter = boundaries.DOMAIN_MODULES[module_name]
    assert "kicad_mcp.tools.manufacturing" not in boundaries._imports_for(module_name, adapter)
    span = boundaries._function_span(adapter, "register")
    assert span is not None
    assert span <= 90
    assert boundaries.REGISTER_LINE_LIMITS[module_name] == 90


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
    assert span <= 590


def test_validation_uses_domain_release_file_helper_not_tool_monolith() -> None:
    validation = Path(boundaries.SRC_ROOT / "kicad_mcp" / "tools" / "validation.py")
    source = validation.read_text(encoding="utf-8")
    assert "from .manufacturing import _find_release_files" not in source
    assert "from ..manufacturing.release_evidence import find_release_files" in source

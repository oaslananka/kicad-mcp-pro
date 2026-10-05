from __future__ import annotations

import ast

from scripts import check_architecture_boundaries as boundaries


def test_architecture_checker_tracks_si_stackup_generation_service_and_adapter() -> None:
    assert "kicad_mcp.signal_integrity.stackup_generation" in boundaries.DOMAIN_MODULES
    assert "kicad_mcp.signal_integrity.stackup_generation" in boundaries.PURE_HELPERS
    assert "kicad_mcp.tools.signal_integrity_stackup_generation" in boundaries.DOMAIN_MODULES
    assert "kicad_mcp.tools.signal_integrity" in boundaries.DOMAIN_MODULES


def test_si_stackup_generation_adapter_stays_thin_and_away_from_root() -> None:
    module_name = "kicad_mcp.tools.signal_integrity_stackup_generation"
    adapter = boundaries.DOMAIN_MODULES[module_name]
    assert "kicad_mcp.tools.signal_integrity" not in boundaries._imports_for(
        module_name,
        adapter,
    )
    span = boundaries._function_span(adapter, "register")
    assert span is not None
    assert span <= 75
    assert boundaries.REGISTER_LINE_LIMITS[module_name] == 75


def test_si_root_delegates_stackup_generation_and_shrinks() -> None:
    root = boundaries.DOMAIN_MODULES["kicad_mcp.tools.signal_integrity"]
    tree = ast.parse(root.read_text(encoding="utf-8"), filename=str(root))
    register_node = next(
        node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "register"
    )
    nested = {
        node.name
        for node in register_node.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }

    assert "si_generate_stackup" not in nested
    span = boundaries._function_span(root, "register")
    assert span is not None
    assert span <= 620
    assert boundaries.REGISTER_LINE_LIMITS["kicad_mcp.tools.signal_integrity"] <= 620


def test_si_root_drops_stackup_generation_only_dependencies() -> None:
    root = boundaries.DOMAIN_MODULES["kicad_mcp.tools.signal_integrity"]
    source = root.read_text(encoding="utf-8")

    assert "StackupInput" not in source
    assert "def _stackup_templates(" not in source

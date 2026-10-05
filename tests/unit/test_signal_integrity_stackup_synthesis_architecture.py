from __future__ import annotations

import ast

from scripts import check_architecture_boundaries as boundaries

SERVICE = "kicad_mcp.signal_integrity.stackup_synthesis"
ADAPTER = "kicad_mcp.tools.signal_integrity_stackup_synthesis"
ROOT = "kicad_mcp.tools.signal_integrity"


def test_architecture_checker_tracks_si_stackup_synthesis_service_and_adapter() -> None:
    assert SERVICE in boundaries.DOMAIN_MODULES
    assert SERVICE in boundaries.PURE_HELPERS
    assert ADAPTER in boundaries.DOMAIN_MODULES
    assert ROOT in boundaries.DOMAIN_MODULES


def test_si_stackup_synthesis_adapter_stays_thin_and_away_from_root() -> None:
    adapter = boundaries.DOMAIN_MODULES[ADAPTER]
    assert ROOT not in boundaries._imports_for(ADAPTER, adapter)
    assert boundaries.ADAPTER_FORBIDDEN_IMPORT_PREFIXES[ADAPTER] == (ROOT,)
    span = boundaries._function_span(adapter, "register")
    assert span is not None
    assert span <= 75
    assert boundaries.REGISTER_LINE_LIMITS[ADAPTER] == 75


def test_si_root_delegates_stackup_synthesis_and_shrinks() -> None:
    root = boundaries.DOMAIN_MODULES[ROOT]
    tree = ast.parse(root.read_text(encoding="utf-8"), filename=str(root))
    register_node = next(
        node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "register"
    )
    nested = {
        node.name
        for node in register_node.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }

    assert "si_synthesize_stackup_for_interfaces" not in nested
    span = boundaries._function_span(root, "register")
    assert span is not None
    assert span <= 390
    assert boundaries.REGISTER_LINE_LIMITS[ROOT] == 390


def test_si_root_drops_stackup_synthesis_only_dependencies() -> None:
    root = boundaries.DOMAIN_MODULES[ROOT]
    source = root.read_text(encoding="utf-8")

    assert "DIELECTRIC_LIBRARY" not in source
    assert "get_dielectric" not in source
    assert "recommend_dielectric_for_frequency" not in source
    assert "solve_spacing_for_differential_impedance" not in source
    assert "solve_width_for_impedance" not in source

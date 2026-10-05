from __future__ import annotations

import ast

from scripts import check_architecture_boundaries as boundaries

SERVICE = "kicad_mcp.signal_integrity.decoupling_placement"
ADAPTER = "kicad_mcp.tools.signal_integrity_decoupling_placement"
ROOT = "kicad_mcp.tools.signal_integrity"


def test_architecture_checker_tracks_decoupling_service_and_adapter() -> None:
    assert SERVICE in boundaries.DOMAIN_MODULES
    assert SERVICE in boundaries.PURE_HELPERS
    assert ADAPTER in boundaries.DOMAIN_MODULES
    assert ROOT in boundaries.DOMAIN_MODULES


def test_decoupling_adapter_stays_thin_and_away_from_root() -> None:
    adapter = boundaries.DOMAIN_MODULES[ADAPTER]
    assert ROOT not in boundaries._imports_for(ADAPTER, adapter)
    assert boundaries.ADAPTER_FORBIDDEN_IMPORT_PREFIXES[ADAPTER] == (ROOT,)
    span = boundaries._function_span(adapter, "register")
    assert span is not None
    assert span <= 40
    assert boundaries.REGISTER_LINE_LIMITS[ADAPTER] == 40


def test_si_root_delegates_decoupling_and_shrinks() -> None:
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
    source = root.read_text(encoding="utf-8")

    assert "si_calculate_decoupling_placement" not in nested
    assert "DecouplingPlacementInput" not in source
    assert "_find_power_anchor" not in source
    assert "_nearest_capacitors" not in source
    assert "recommended_decoupling_distance_mm" not in source
    assert "signal_integrity_decoupling_placement.register(mcp)" in source

    span = boundaries._function_span(root, "register")
    assert span is not None
    assert span <= 105
    assert boundaries.REGISTER_LINE_LIMITS[ROOT] <= 105

from __future__ import annotations

import ast

from scripts import check_architecture_boundaries as boundaries

SERVICE = "kicad_mcp.signal_integrity.differential_pair_skew"
ADAPTER = "kicad_mcp.tools.signal_integrity_differential_pair_skew"
ROOT = "kicad_mcp.tools.signal_integrity"


def test_architecture_checker_tracks_skew_service_and_adapter() -> None:
    assert SERVICE in boundaries.DOMAIN_MODULES
    assert SERVICE in boundaries.PURE_HELPERS
    assert ADAPTER in boundaries.DOMAIN_MODULES
    assert ROOT in boundaries.DOMAIN_MODULES


def test_skew_adapter_stays_thin_and_away_from_root() -> None:
    adapter = boundaries.DOMAIN_MODULES[ADAPTER]
    assert ROOT not in boundaries._imports_for(ADAPTER, adapter)
    assert boundaries.ADAPTER_FORBIDDEN_IMPORT_PREFIXES[ADAPTER] == (ROOT,)
    span = boundaries._function_span(adapter, "register")
    assert span is not None
    assert span <= 45
    assert boundaries.REGISTER_LINE_LIMITS[ADAPTER] == 45


def test_si_root_delegates_skew_and_shrinks() -> None:
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

    assert "si_check_differential_pair_skew" not in nested
    assert "DifferentialPairSkewInput" not in source
    assert "_resolve_skew_budget_ps" not in source
    assert "_track_lengths_by_net" not in source
    assert "_track_width_mm" not in source
    assert "_outer_dielectric_height_mm" not in source
    assert "signal_integrity_differential_pair_skew.register(mcp)" in source

    span = boundaries._function_span(root, "register")
    assert span is not None
    assert span <= 150
    assert boundaries.REGISTER_LINE_LIMITS[ROOT] == 150

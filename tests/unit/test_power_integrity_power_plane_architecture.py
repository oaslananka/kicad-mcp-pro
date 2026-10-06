from __future__ import annotations

import ast

from scripts import check_architecture_boundaries as boundaries

SERVICE = "kicad_mcp.power_integrity.power_plane"
ADAPTER = "kicad_mcp.tools.power_integrity_power_plane"
ROOT = "kicad_mcp.tools.power_integrity"


def test_architecture_checker_tracks_power_plane_service_and_adapter() -> None:
    assert SERVICE in boundaries.DOMAIN_MODULES
    assert SERVICE in boundaries.PURE_HELPERS
    assert ADAPTER in boundaries.DOMAIN_MODULES


def test_power_plane_adapter_stays_away_from_root_and_register_is_thin() -> None:
    adapter = boundaries.DOMAIN_MODULES[ADAPTER]
    assert ROOT not in boundaries._imports_for(ADAPTER, adapter)
    assert boundaries.ADAPTER_FORBIDDEN_IMPORT_PREFIXES[ADAPTER] == (ROOT,)
    span = boundaries._function_span(adapter, "register")
    assert span is not None
    assert span <= 30
    assert boundaries.REGISTER_LINE_LIMITS[ADAPTER] == 30


def test_pi_root_is_composition_only_after_final_extraction() -> None:
    root = boundaries.DOMAIN_MODULES[ROOT]
    tree = ast.parse(root.read_text(encoding="utf-8"), filename=str(root))
    register_node = next(
        node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "register"
    )
    nested = [
        node.name
        for node in register_node.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    imports = boundaries._imports_for(ROOT, root)
    source = root.read_text(encoding="utf-8")

    assert nested == []
    assert "power_integrity_power_plane.register(mcp)" in source
    assert "execute_live_board_mutation" not in source
    assert "get_board" not in source
    assert not any(name.startswith("kipy") for name in imports)

    span = boundaries._function_span(root, "register")
    assert span is not None
    assert span <= 30
    assert boundaries.REGISTER_LINE_LIMITS[ROOT] <= 30

from __future__ import annotations

import ast

from scripts import check_architecture_boundaries as boundaries

SERVICE = "kicad_mcp.power_integrity.pdn_mesh_check"
ADAPTER = "kicad_mcp.tools.power_integrity_pdn_mesh"
ROOT = "kicad_mcp.tools.power_integrity"


def test_architecture_checker_tracks_pdn_mesh_service_and_adapter() -> None:
    assert SERVICE in boundaries.DOMAIN_MODULES
    assert SERVICE in boundaries.PURE_HELPERS
    assert ADAPTER in boundaries.DOMAIN_MODULES


def test_pdn_mesh_adapter_stays_thin_and_away_from_root() -> None:
    adapter = boundaries.DOMAIN_MODULES[ADAPTER]
    assert ROOT not in boundaries._imports_for(ADAPTER, adapter)
    assert boundaries.ADAPTER_FORBIDDEN_IMPORT_PREFIXES[ADAPTER] == (ROOT,)
    span = boundaries._function_span(adapter, "register")
    assert span is not None
    assert span <= 55
    assert boundaries.REGISTER_LINE_LIMITS[ADAPTER] == 55


def test_pi_root_delegates_pdn_mesh_and_shrinks() -> None:
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

    assert "check_power_integrity" not in nested
    assert "PdnMesh" not in source
    assert "PdnLoad" not in source
    assert "PdnDecouplingCap" not in source
    assert "pdn_mesh_method" not in source
    assert "power_integrity_pdn_mesh.register(mcp)" in source

    span = boundaries._function_span(root, "register")
    assert span is not None
    assert span <= 300
    assert boundaries.REGISTER_LINE_LIMITS[ROOT] <= 300

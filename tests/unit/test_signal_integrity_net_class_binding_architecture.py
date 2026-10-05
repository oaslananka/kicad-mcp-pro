from __future__ import annotations

import ast

from scripts import check_architecture_boundaries as boundaries

SERVICE = "kicad_mcp.signal_integrity.net_class_binding"
ADAPTER = "kicad_mcp.tools.signal_integrity_net_class_binding"
ROOT = "kicad_mcp.tools.signal_integrity"


def test_architecture_checker_tracks_si_net_class_binding_service_and_adapter() -> None:
    assert SERVICE in boundaries.DOMAIN_MODULES
    assert SERVICE in boundaries.PURE_HELPERS
    assert ADAPTER in boundaries.DOMAIN_MODULES
    assert ROOT in boundaries.DOMAIN_MODULES


def test_si_net_class_binding_adapter_stays_thin_and_away_from_root() -> None:
    adapter = boundaries.DOMAIN_MODULES[ADAPTER]
    assert ROOT not in boundaries._imports_for(ADAPTER, adapter)
    assert boundaries.ADAPTER_FORBIDDEN_IMPORT_PREFIXES[ADAPTER] == (ROOT,)
    span = boundaries._function_span(adapter, "register")
    assert span is not None
    assert span <= 65
    assert boundaries.REGISTER_LINE_LIMITS[ADAPTER] == 65


def test_si_root_delegates_net_class_binding_and_shrinks() -> None:
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

    assert "si_bind_interfaces_to_net_classes" not in nested
    span = boundaries._function_span(root, "register")
    assert span is not None
    assert span <= 270
    assert boundaries.REGISTER_LINE_LIMITS[ROOT] == 270


def test_si_root_drops_net_class_rule_writer_ownership() -> None:
    root = boundaries.DOMAIN_MODULES[ROOT]
    source = root.read_text(encoding="utf-8")

    assert "_write_nc_rule" not in source
    assert "signal_integrity_net_class_binding.register(mcp)" in source

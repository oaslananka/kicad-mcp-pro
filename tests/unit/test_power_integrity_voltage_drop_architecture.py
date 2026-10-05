from __future__ import annotations

import ast

from scripts import check_architecture_boundaries as boundaries

SERVICE = "kicad_mcp.power_integrity.voltage_drop"
ADAPTER = "kicad_mcp.tools.power_integrity_voltage_drop"
ROOT = "kicad_mcp.tools.power_integrity"


def test_architecture_checker_tracks_voltage_drop_service_and_adapter() -> None:
    assert SERVICE in boundaries.DOMAIN_MODULES
    assert SERVICE in boundaries.PURE_HELPERS
    assert ADAPTER in boundaries.DOMAIN_MODULES
    assert ROOT in boundaries.DOMAIN_MODULES


def test_voltage_drop_adapter_stays_thin_and_away_from_root() -> None:
    adapter = boundaries.DOMAIN_MODULES[ADAPTER]
    assert ROOT not in boundaries._imports_for(ADAPTER, adapter)
    assert boundaries.ADAPTER_FORBIDDEN_IMPORT_PREFIXES[ADAPTER] == (ROOT,)
    span = boundaries._function_span(adapter, "register")
    assert span is not None
    assert span <= 50
    assert boundaries.REGISTER_LINE_LIMITS[ADAPTER] == 50


def test_pi_root_delegates_voltage_drop_and_shrinks() -> None:
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

    assert "pdn_calculate_voltage_drop" not in nested
    assert "VoltageDropInput" not in source
    assert "ipc2221_temperature_rise_c" not in source
    assert "ir_drop_method" not in source
    assert "power_integrity_voltage_drop.register(mcp)" in source

    span = boundaries._function_span(root, "register")
    assert span is not None
    assert span <= 510
    assert boundaries.REGISTER_LINE_LIMITS[ROOT] <= 510

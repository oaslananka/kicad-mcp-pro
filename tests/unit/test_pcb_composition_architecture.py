"""Architecture guards for the bounded PCB composition root."""

from __future__ import annotations

import ast
from pathlib import Path

PCB_MODULE = Path("src/kicad_mcp/tools/pcb.py")
MAX_REGISTER_LINES = 300
EXPECTED_HELPERS = {
    "_register_impedance_and_creepage_tools",
    "_register_board_rules_tools",
    "_register_routing_authoring_tools",
    "_register_board_graphics_tools",
    "_register_board_mutation_tools",
    "_register_schematic_sync_tools",
    "_register_placement_automation_tools",
    "_register_zone_authoring_tools",
    "_register_mechanical_and_block_tools",
    "_register_teardrop_tools",
    "_register_advanced_placement_tools",
    "_register_placement_critique_tools",
}


def _top_level_functions() -> dict[str, ast.FunctionDef]:
    tree = ast.parse(PCB_MODULE.read_text(encoding="utf-8"))
    return {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}


def _span(node: ast.FunctionDef) -> int:
    assert node.end_lineno is not None
    return node.end_lineno - node.lineno + 1


def test_pcb_register_and_composition_helpers_stay_bounded() -> None:
    functions = _top_level_functions()
    assert EXPECTED_HELPERS <= functions.keys()
    assert _span(functions["register"]) <= MAX_REGISTER_LINES
    for name in EXPECTED_HELPERS:
        assert _span(functions[name]) <= MAX_REGISTER_LINES, name


def test_pcb_register_contains_no_nested_tool_definitions() -> None:
    register = _top_level_functions()["register"]
    nested = [
        node.name
        for node in register.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    assert nested == []

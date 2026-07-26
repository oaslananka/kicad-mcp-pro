from __future__ import annotations

import ast
from pathlib import Path

from scripts.check_architecture_boundaries import DOMAIN_MODULES, REGISTER_LINE_LIMITS

ROOT = Path(__file__).resolve().parents[2]
SCHEMATIC = ROOT / "src" / "kicad_mcp" / "tools" / "schematic.py"


def _function_span(name: str) -> int:
    tree = ast.parse(SCHEMATIC.read_text(encoding="utf-8"), filename=str(SCHEMATIC))
    matches = [
        node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == name
    ]
    assert len(matches) == 1
    node = matches[0]
    assert node.end_lineno is not None
    return node.end_lineno - node.lineno + 1


def test_schematic_composition_functions_stay_below_300_lines() -> None:
    assert _function_span("register") <= 300
    assert _function_span("_register_inspection_and_analysis") <= 300
    assert _function_span("_register_authoring") <= 300


def test_architecture_checker_enforces_schematic_composition_limit() -> None:
    assert DOMAIN_MODULES["kicad_mcp.tools.schematic"] == SCHEMATIC
    assert REGISTER_LINE_LIMITS["kicad_mcp.tools.schematic"] == 300

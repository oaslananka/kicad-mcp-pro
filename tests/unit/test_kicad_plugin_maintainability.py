from __future__ import annotations

import ast
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[2] / "packages/kicad-plugin/kicad_mcp_companion.py"


def test_companion_title_literal_is_defined_once() -> None:
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    literal = "kicad-mcp companion"
    occurrences = sum(
        isinstance(node, ast.Constant) and node.value == literal for node in ast.walk(tree)
    )

    assert occurrences == 1

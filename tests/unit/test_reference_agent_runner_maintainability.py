from __future__ import annotations

import ast
from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parents[2] / "src/kicad_mcp/evals/reference_agent_runner.py"


@pytest.mark.parametrize(
    "literal",
    [
        "reference source revision could not be resolved",
        "manufacturing approval approved project files are invalid",
    ],
)
def test_repeated_runner_error_messages_are_defined_once(literal: str) -> None:
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    occurrences = sum(
        isinstance(node, ast.Constant) and node.value == literal for node in ast.walk(tree)
    )

    assert occurrences == 1

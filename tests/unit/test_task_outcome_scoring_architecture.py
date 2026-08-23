from __future__ import annotations

import ast
from pathlib import Path

SCORING_MODULE = Path("src/kicad_mcp/evals/task_outcome_scoring.py")


def test_task_outcome_aggregate_stays_reviewably_small() -> None:
    tree = ast.parse(SCORING_MODULE.read_text(encoding="utf-8"), filename=str(SCORING_MODULE))
    aggregate = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "aggregate_task_outcomes"
    )

    assert aggregate.end_lineno is not None
    assert aggregate.end_lineno - aggregate.lineno + 1 <= 80

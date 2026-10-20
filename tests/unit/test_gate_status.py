from __future__ import annotations

from collections.abc import Callable
from types import SimpleNamespace

import pytest

from kicad_mcp.project.reporting import _combined_status as reporting_status
from kicad_mcp.project.validation_loops import _combined_status as loop_status
from kicad_mcp.tools.gates import _combined_status as tool_status


@pytest.mark.parametrize("combine", [tool_status, reporting_status, loop_status])
@pytest.mark.parametrize(
    ("statuses", "expected"),
    [
        ([], "PASS"),
        (["PASS", "PASS"], "PASS"),
        (["PASS", "WARN"], "WARN"),
        (["WARN", "FAIL"], "FAIL"),
        (["FAIL", "BLOCKED"], "BLOCKED"),
        (["BLOCKED", "EMPTY"], "EMPTY"),
        (["EMPTY", "WARN", "FAIL", "BLOCKED", "PASS"], "EMPTY"),
        (["UNRECOGNIZED"], "PASS"),
    ],
)
def test_gate_status_precedence_across_consumers(
    combine: Callable[..., str], statuses: list[str], expected: str
) -> None:
    outcomes = [SimpleNamespace(status=status) for status in statuses]
    assert combine(outcomes) == expected
    assert combine(list(reversed(outcomes))) == expected

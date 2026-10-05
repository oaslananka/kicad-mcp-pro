from __future__ import annotations

import importlib
import inspect
from typing import Any, cast

from mcp.server.mcpserver import MCPServer as FastMCP


class FakeService:
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []

    def validate(
        self,
        net_groups: list[list[str]],
        tolerance_mm: float,
        lengths: dict[str, float],
    ) -> str:
        self.calls.append((net_groups, tolerance_mm, lengths))
        return "length-result"


def test_registration_preserves_signature_docstring_and_delegation() -> None:
    adapter = importlib.import_module("kicad_mcp.tools.signal_integrity_length_matching")
    server = FastMCP("si-length-matching-registration")
    service = FakeService()

    adapter.register(
        server,
        adapter.SignalIntegrityLengthMatchingDependencies(
            service=cast(Any, service),
            track_length_provider=lambda: {"A": 10.0, "B": 10.5},
        ),
    )

    tool_list = server._tool_manager.list_tools()
    assert [tool.name for tool in tool_list] == ["si_validate_length_matching"]

    tool = tool_list[0]
    assert str(inspect.signature(tool.fn)) == (
        "(net_groups: 'list[list[str]]', tolerance_mm: 'float' = 2.0) -> 'str'"
    )
    assert tool.fn.__doc__ == (
        "Validate that each net group is matched within the supplied tolerance."
    )

    assert tool.fn([["A", "B"]], 1.0) == "length-result"
    assert service.calls == [([["A", "B"]], 1.0, {"A": 10.0, "B": 10.5})]

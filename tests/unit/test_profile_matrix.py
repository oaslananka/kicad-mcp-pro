from __future__ import annotations

import pytest

from kicad_mcp.operating_modes import OperatingMode, is_tool_allowed_in_mode
from kicad_mcp.server import build_server
from kicad_mcp.tools.router import EXPERIMENTAL_TOOL_NAMES, PROFILE_CATEGORIES, tools_for_profile


def _default_mode_expected_tools(profile_name: str, expected: list[str]) -> set[str]:
    names = set(expected)
    if profile_name != "agent_full":
        names -= EXPERIMENTAL_TOOL_NAMES
    return {name for name in names if is_tool_allowed_in_mode(name, OperatingMode.READONLY)}


@pytest.mark.anyio
async def test_profile_tool_matrix_matches_declared_categories(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "kicad_mcp.server.get_ipc_capability_state",
        lambda: _AvailableIpcState(),
    )
    for profile_name, categories in PROFILE_CATEGORIES.items():
        server = build_server(profile_name)
        listed = [tool.name for tool in await server.list_tools()]
        listed_set = set(listed)
        expected = list(tools_for_profile(profile_name))

        assert categories
        assert len(listed) == len(listed_set)
        assert listed_set.issubset(set(expected))
        assert listed_set == _default_mode_expected_tools(profile_name, expected)


class _AvailableIpcState:
    reachable = True
    live_pcb_read = True
    live_pcb_write = True
    live_schematic_read = True
    live_schematic_write = True
    operations: dict[str, object] = {}

    def tool_available(self, _tool_name: str) -> bool:
        return True

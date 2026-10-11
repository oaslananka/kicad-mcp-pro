"""Newly surfaced tools (work order P1-T2).

These tools were previously registered but declared in no router category, so they
were filtered out of every profile and hidden from discovery. P1-T2 surface curation
declares them in their natural categories. This test pins that fix per tool: each must
be both registered and declared in a category (so it is reachable in some profile).
"""

from __future__ import annotations

import pytest

from kicad_mcp.tools.router import TOOL_CATEGORIES

SURFACED_TOOLS = [
    "pcb_get_groups",
    "pcb_get_origin",
    "pcb_set_origin",
    "pcb_set_title_block_info",
    "pcb_import_board",
    "pcb_begin_commit",
    "pcb_push_commit",
    "pcb_drop_commit",
    "pcb_revert",
    "jobset_run",
    "jobset_validate",
    "fp_export_svg",
    "sym_export_svg",
]


def _declared_tool_names() -> set[str]:
    names: set[str] = set()
    for category in TOOL_CATEGORIES.values():
        names.update(category["tools"])
    return names


@pytest.mark.parametrize("tool_name", SURFACED_TOOLS)
def test_surfaced_tool_registered_and_declared(
    tool_name: str, registered_tool_names: set[str]
) -> None:
    assert tool_name in registered_tool_names, f"{tool_name} is not registered"
    assert tool_name in _declared_tool_names(), f"{tool_name} is not declared in any category"

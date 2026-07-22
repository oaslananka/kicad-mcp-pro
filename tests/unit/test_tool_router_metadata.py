"""Unit tests for tool router metadata and category discovery (FAZ 15)."""

from __future__ import annotations

from kicad_mcp.tools.router import (
    EXPERIMENTAL_TOOL_NAMES,
    TOOL_CATEGORIES,
    available_profiles,
    categories_for_profile,
    tool_count_for_profile,
    tools_for_profile,
)


def test_tool_categories_contain_required() -> None:
    required = {"project", "pcb_read", "pcb_write", "schematic", "library", "export", "validation"}
    for cat in required:
        assert cat in TOOL_CATEGORIES, f"Missing category: {cat}"


def test_every_category_has_tools() -> None:
    for cat, info in TOOL_CATEGORIES.items():
        assert len(info["tools"]) > 0, f"Category '{cat}' has no tools"


def test_experimental_tools_listed_in_tool_categories() -> None:
    all_tools = set()
    for info in TOOL_CATEGORIES.values():
        all_tools.update(info["tools"])
    for exp in EXPERIMENTAL_TOOL_NAMES:
        assert exp in all_tools, f"Experimental tool '{exp}' not registered in any category"


def test_available_profiles_contain_full() -> None:
    profiles = available_profiles()
    assert "full" in profiles


def test_categories_for_profile_full() -> None:
    cats = categories_for_profile("full")
    assert len(cats) == len(TOOL_CATEGORIES)


def test_profiles_do_not_include_unknown() -> None:
    cats = categories_for_profile("nobody")
    assert cats == categories_for_profile("default")  # fail closed


def test_tools_for_profile_returns_unique_tool_count() -> None:
    tools = tools_for_profile("full")

    assert len(tools) == len(set(tools))
    assert tool_count_for_profile("full") == len(tools)
    assert tool_count_for_profile("unknown-profile") == tool_count_for_profile("default")
    assert tool_count_for_profile("minimal") < tool_count_for_profile("full")

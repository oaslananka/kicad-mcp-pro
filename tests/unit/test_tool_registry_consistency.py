"""Tool-router registry consistency invariants (work order P0-T2).

These guard the failure modes called out in the hardening work order:

* (a) a name listed in ``router.TOOL_CATEGORIES`` that maps to no real ``@mcp.tool``
* (b) a profile that references a category that does not exist
* (c) the same tool name claimed by two different categories
* (d) experimental tools that are not actually registered

Registration completeness is checked against the raw tool manager (the
*unfiltered* registered set), so these assertions are independent of the active
profile and operating-mode filtering applied by ``KiCadFastMCP.list_tools``.

It also enforces that there are no orphaned tools — registered tools that appear in
no category and would therefore be hidden from discovery in every profile (resolved
by the P1-T2 surface curation).
"""

from __future__ import annotations

from collections import Counter

from kicad_mcp.tools.router import (
    EXPERIMENTAL_TOOL_NAMES,
    PROFILE_CATEGORIES,
    TOOL_CATEGORIES,
)


def _declared_tool_names() -> list[str]:
    """Every tool name declared across all router categories (with repeats)."""
    names: list[str] = []
    for info in TOOL_CATEGORIES.values():
        names.extend(info["tools"])
    return names


# --- (b) every profile references existing categories -----------------------


def test_profiles_reference_existing_categories() -> None:
    for profile, categories in PROFILE_CATEGORIES.items():
        for category in categories:
            assert category in TOOL_CATEGORIES, (
                f"Profile '{profile}' references unknown category '{category}'"
            )


# --- (c) tool names are unique across and within categories -----------------


def test_no_tool_in_multiple_categories() -> None:
    where: dict[str, list[str]] = {}
    for category, info in TOOL_CATEGORIES.items():
        for tool_name in info["tools"]:
            where.setdefault(tool_name, []).append(category)
    duplicates = {name: cats for name, cats in where.items() if len(cats) > 1}
    assert not duplicates, f"Tool names claimed by multiple categories: {duplicates}"


def test_no_duplicate_tool_within_a_category() -> None:
    for category, info in TOOL_CATEGORIES.items():
        counts = Counter(info["tools"])
        dupes = {name: count for name, count in counts.items() if count > 1}
        assert not dupes, f"Category '{category}' lists duplicate tools: {dupes}"


def test_every_category_has_tools() -> None:
    for category, info in TOOL_CATEGORIES.items():
        assert info["tools"], f"Category '{category}' declares no tools"


# --- (a)/(d) declared and experimental tools are really registered ----------


def test_declared_tools_are_registered(registered_tool_names: set[str]) -> None:
    missing = sorted(set(_declared_tool_names()) - registered_tool_names)
    assert not missing, f"Declared in a category but not registered as @mcp.tool: {missing}"


def test_experimental_tools_are_registered(registered_tool_names: set[str]) -> None:
    missing = sorted(EXPERIMENTAL_TOOL_NAMES - registered_tool_names)
    assert not missing, f"Experimental tools not registered: {missing}"


def test_experimental_tools_are_declared_in_a_category() -> None:
    declared = set(_declared_tool_names())
    missing = sorted(EXPERIMENTAL_TOOL_NAMES - declared)
    assert not missing, f"Experimental tools not declared in any category: {missing}"


# --- no orphaned registered tools (every registered tool is discoverable) ----


def test_no_orphaned_registered_tools(registered_tool_names: set[str]) -> None:
    """Every registered tool must be declared in a category (else it is hidden from
    discovery in every profile). Resolved in P1-T2 surface curation."""
    orphans = sorted(registered_tool_names - set(_declared_tool_names()))
    assert not orphans, f"Registered tools missing from every category: {orphans}"

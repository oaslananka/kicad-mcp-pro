from __future__ import annotations

from pathlib import Path

import pytest

from kicad_mcp.capabilities import AccessTier, all_records
from kicad_mcp.capabilities import tools_for_profile as capability_tools
from kicad_mcp.config import KiCadMCPConfig
from kicad_mcp.server import build_server
from kicad_mcp.tools.router import (
    PROFILE_TOOL_ALLOWLISTS,
    TOOL_CATEGORIES,
    available_profiles,
    categories_for_profile,
    tools_for_profile,
)
from kicad_mcp.tools.router import (
    register as register_router,
)
from tests.conftest import call_tool_text

WORKFLOW_PROFILES = ("default", "review", "build", "release", "expert")


def test_default_configuration_uses_bounded_profile(tmp_path: Path) -> None:
    cli = tmp_path / "kicad-cli"
    cli.write_text("#!/bin/sh\n", encoding="utf-8")
    cli.chmod(0o755)
    config = KiCadMCPConfig(kicad_cli=cli)

    assert config.profile == "default"
    assert len(tools_for_profile(config.profile)) < 25


def test_workflow_profiles_are_public_and_bounded() -> None:
    assert set(WORKFLOW_PROFILES).issubset(available_profiles())
    assert tools_for_profile("default") == tools_for_profile("review")
    assert len(tools_for_profile("review")) == 24
    assert len(tools_for_profile("build")) == 24
    assert len(tools_for_profile("release")) == 24
    assert tools_for_profile("expert") == tools_for_profile("full")


def test_review_profile_is_read_only() -> None:
    records = all_records()

    assert tools_for_profile("review")
    assert all(records[name].tier is AccessTier.READ for name in tools_for_profile("review"))


def test_build_profile_enforces_transactional_workflows() -> None:
    surfaced = set(tools_for_profile("build"))

    assert {
        "sch_plan_from_spec",
        "sch_preview_plan",
        "sch_apply_plan",
        "sch_verify_plan",
        "sch_rollback_plan",
    }.issubset(surfaced)
    assert {"pcb_begin_commit", "pcb_push_commit", "pcb_drop_commit", "pcb_revert"}.issubset(
        surfaced
    )
    assert {"vcs_commit_checkpoint", "vcs_diff_with_checkpoint"}.issubset(surfaced)
    assert "pcb_delete_items" not in surfaced
    assert "sch_delete_symbol" not in surfaced


def test_release_profile_keeps_human_gated_export_boundary() -> None:
    records = all_records()
    surfaced = set(tools_for_profile("release"))

    assert {"run_drc", "run_erc", "validate_design", "dfm_run_manufacturer_check"}.issubset(
        surfaced
    )
    assert {
        "get_board_stats",
        "project_quality_gate",
        "manufacturing_quality_gate",
        "export_manufacturing_package",
    }.issubset(surfaced)
    assert records["export_manufacturing_package"].tier is AccessTier.HUMAN_ONLY
    assert records["export_manufacturing_package"].human_gate_required
    assert "export_gerber" not in surfaced
    assert "vcs_commit_checkpoint" not in surfaced
    assert "vcs_tag_release" not in surfaced


def test_review_profile_covers_golden_selection_cases_without_forbidden_tools() -> None:
    from kicad_mcp.evals.tool_selection import load_cases

    cases_path = Path(__file__).resolve().parents[2] / "evals" / "tool_selection" / "cases.yaml"
    surfaced = set(tools_for_profile("review"))
    cases = [case for case in load_cases(cases_path) if "review-profile" in case.tags]

    assert cases
    assert all(case.safety == "read_only" for case in cases)
    assert all(set(case.expected_tools).issubset(surfaced) for case in cases)
    assert all(set(case.forbidden_tools).isdisjoint(surfaced) for case in cases)


def test_capability_registry_matches_exact_profile_allowlists() -> None:
    for profile, tools in PROFILE_TOOL_ALLOWLISTS.items():
        registered = {record.name for record in capability_tools(profile)}
        assert registered == set(tools)


def test_explicit_profile_categories_are_derived_from_allowlists() -> None:
    category_by_tool = {
        tool: category for category, info in TOOL_CATEGORIES.items() for tool in info["tools"]
    }

    for profile, tools in PROFILE_TOOL_ALLOWLISTS.items():
        categories = categories_for_profile(profile)
        assert categories
        assert set(categories) == {category_by_tool[tool] for tool in tools}
        assert tools_for_profile(profile) == tools


@pytest.mark.anyio
async def test_default_discovery_hides_tools_outside_profile() -> None:
    server = build_server("default")

    categories = await call_tool_text(server, "kicad_list_tool_categories", {})
    project_tools = await call_tool_text(
        server, "kicad_get_tools_in_category", {"category": "project"}
    )
    hidden_category = await call_tool_text(
        server, "kicad_get_tools_in_category", {"category": "pcb_write"}
    )

    assert "## `pcb_write`" not in categories
    assert "## `routing`" not in categories
    assert "project_auto_fix_loop" not in project_tools
    assert "project_get_next_action" in project_tools
    assert "Unknown or unavailable category 'pcb_write'" in hidden_category
    assert "pcb_write" not in hidden_category.split("Available categories:", 1)[-1]


def test_discovery_without_allowlist_preserves_full_legacy_visibility() -> None:
    registered: dict[str, object] = {}

    class LegacyMCP:
        def tool(self):  # type: ignore[no-untyped-def]
            def decorator(func):  # type: ignore[no-untyped-def]
                registered[func.__name__] = func
                return func

            return decorator

    register_router(LegacyMCP())  # type: ignore[arg-type]
    list_categories = registered["kicad_list_tool_categories"]

    output = list_categories()  # type: ignore[operator]

    assert "## `pcb_write`" in output
    assert "## `release_export`" in output


def test_unknown_profile_fails_closed_to_default() -> None:
    assert tools_for_profile("unknown-profile") == tools_for_profile("default")
    assert categories_for_profile("unknown-profile") == categories_for_profile("default")

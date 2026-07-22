from __future__ import annotations

import pytest

from kicad_mcp.operating_modes import OperatingMode, is_tool_allowed_in_mode
from kicad_mcp.server import build_server, create_server
from kicad_mcp.tools.router import (
    EXPERIMENTAL_TOOL_NAMES,
    PROFILE_CATEGORIES,
    TOOL_CATEGORIES,
    available_profiles,
    categories_for_profile,
)
from tests.conftest import call_tool_text


def test_available_profiles_include_v2_surface() -> None:
    expected = {
        "full",
        "expert",
        "minimal",
        "beginner",
        "read_only_inspection",
        "schematic_only",
        "schematic_authoring",
        "pcb_only",
        "pcb_layout",
        "manufacturing",
        "manufacturing_release",
        "builder",
        "critic",
        "release_manager",
        "high_speed",
        "power",
        "simulation",
        "analysis",
        "agent_full",
        "pcb",
        "schematic",
    }

    assert expected.issubset(set(available_profiles()))
    assert categories_for_profile("analysis") == PROFILE_CATEGORIES["analysis"]
    assert categories_for_profile("expert") == PROFILE_CATEGORIES["full"]
    assert "pcb_write" not in categories_for_profile("read_only_inspection")
    assert "schematic" in categories_for_profile("schematic_authoring")
    assert "pcb_write" in categories_for_profile("pcb_layout")
    assert "release_export" in categories_for_profile("manufacturing_release")
    for agent_profile in ("builder", "critic", "release_manager"):
        assert categories_for_profile(agent_profile) == PROFILE_CATEGORIES[agent_profile]
        assert categories_for_profile(agent_profile)
    assert "simulation" in PROFILE_CATEGORIES["high_speed"]
    assert "version_control" in PROFILE_CATEGORIES["high_speed"]
    assert categories_for_profile("agent_full") == PROFILE_CATEGORIES["agent_full"]
    assert categories_for_profile("unknown-profile") == PROFILE_CATEGORIES["default"]


def test_validation_cli_tools_are_declared_for_discovery() -> None:
    declared = {
        tool_name for category in TOOL_CATEGORIES.values() for tool_name in category["tools"]
    }

    assert {"run_drc", "run_erc", "validate_design"}.issubset(declared)


def test_oaslana_119_live_editing_aliases_are_declared_for_discovery() -> None:
    declared = {
        tool_name for category in TOOL_CATEGORIES.values() for tool_name in category["tools"]
    }

    assert {
        "pcb_place_component",
        "pcb_route_trace",
        "pcb_add_zone",
        "pcb_set_design_rules",
        "pcb_move_component",
        "pcb_delete_object",
        "sch_add_component",
        "sch_add_wire",
        "sch_modify_property",
    }.issubset(declared)


def test_create_server_sync_wrapper_materializes_tool_list() -> None:
    server = create_server("full")
    tools = server.list_tools()

    assert isinstance(tools, list)
    assert any(tool.name == "kicad_get_version" for tool in tools)


@pytest.mark.anyio
async def test_create_server_sync_wrapper_materializes_tool_list_inside_event_loop() -> None:
    server = create_server("full")
    tools = server.list_tools()

    assert isinstance(tools, list)
    assert any(tool.name == "kicad_get_version" for tool in tools)


@pytest.mark.anyio
async def test_tool_category_output_shows_runtime_metadata() -> None:
    server = build_server("full")

    routing = await call_tool_text(server, "kicad_get_tools_in_category", {"category": "routing"})
    pcb_read = await call_tool_text(server, "kicad_get_tools_in_category", {"category": "pcb_read"})
    release_export = await call_tool_text(
        server,
        "kicad_get_tools_in_category",
        {"category": "release_export"},
    )

    assert "route_autoroute_freerouting [MATURITY:" in routing
    assert "REQUIRES:freerouting" in routing
    assert "pcb_get_tracks" in pcb_read
    assert "HEADLESS" in pcb_read
    assert "export_manufacturing_package [MATURITY:stable / HEADLESS]" in release_export
    assert "get_board_stats [MATURITY:stable / HEADLESS]" in release_export

    stable_pcb_read = await call_tool_text(
        server,
        "kicad_get_tools_in_category",
        {"category": "pcb_read", "maturity": "stable"},
    )
    assert "pcb_get_board_summary" in stable_pcb_read


@pytest.mark.anyio
async def test_tool_category_output_marks_mode_unavailable_tools() -> None:
    server = build_server("full")

    schematic = await call_tool_text(
        server, "kicad_get_tools_in_category", {"category": "schematic"}
    )

    assert "Active operating mode: `readonly`" in schematic
    assert (
        "sch_build_circuit [MATURITY:experimental]` — unavailable in `readonly` "
        "mode; requires `write` mode"
    ) in schematic


@pytest.mark.anyio
@pytest.mark.mcp_mode("write")
async def test_tool_category_output_omits_mode_note_when_tool_is_callable() -> None:
    server = build_server("full")

    schematic = await call_tool_text(
        server, "kicad_get_tools_in_category", {"category": "schematic"}
    )

    assert "Active operating mode: `write`" in schematic
    assert "sch_build_circuit [MATURITY:experimental]`" in schematic
    assert "sch_build_circuit [MATURITY:experimental]` — unavailable" not in schematic


@pytest.mark.anyio
@pytest.mark.mcp_mode("manufacturing")
async def test_manufacturing_profile_exposes_release_exports_only() -> None:
    server = build_server("manufacturing")
    tool_names = {tool.name for tool in await server.list_tools()}

    assert "export_manufacturing_package" in tool_names
    assert "get_board_stats" in tool_names
    assert "export_gerber" not in tool_names
    assert "export_drill" not in tool_names
    assert "export_bom" not in tool_names


@pytest.mark.anyio
async def test_full_profile_keeps_low_level_exports_available() -> None:
    server = build_server("full")
    tool_names = {tool.name for tool in await server.list_tools()}

    assert "export_gerber" in tool_names
    assert "export_drill" in tool_names
    assert "export_bom" in tool_names


@pytest.mark.anyio
async def test_tool_categories_have_no_phantom_or_undeclared_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "kicad_mcp.server.get_ipc_capability_state",
        lambda: _AvailableIpcState(),
    )
    server = build_server("full")
    registered = {tool.name for tool in await server.list_tools()}
    declared: set[str] = set()
    for category in TOOL_CATEGORIES.values():
        declared.update(category["tools"])

    expected = {
        name
        for name in declared - EXPERIMENTAL_TOOL_NAMES
        if is_tool_allowed_in_mode(name, OperatingMode.READONLY)
    }
    assert registered == expected


class _AvailableIpcState:
    reachable = True
    live_pcb_read = True
    live_pcb_write = True
    live_schematic_read = True
    live_schematic_write = True
    operations: dict[str, object] = {}

    def tool_available(self, _tool_name: str) -> bool:
        return True

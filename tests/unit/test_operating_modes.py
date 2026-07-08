from __future__ import annotations

import os

import pytest

from kicad_mcp.config import reset_config
from kicad_mcp.operating_modes import (
    OperatingMode,
    active_operating_mode,
    is_tool_allowed_in_mode,
    tool_required_mode,
)
from kicad_mcp.server import KiCadFastMCP, _apply_cli_env, build_server
from tests.conftest import call_tool_text


def _tool_names_for_mode(mode: str, *, profile: str = "full") -> set[str]:
    os.environ["KICAD_MCP_OPERATING_MODE"] = mode
    reset_config()
    server = build_server(profile)
    assert isinstance(server, KiCadFastMCP)
    server.filter_runtime_tools = False
    return {tool.name for tool in server.list_tools_sync()}


def test_operating_mode_policy_matches_required_risk_levels(monkeypatch) -> None:
    monkeypatch.setenv("KICAD_MCP_OPERATING_MODE", "readonly")
    reset_config()
    assert active_operating_mode().value == "readonly"

    assert tool_required_mode("kicad_get_version") is OperatingMode.READONLY
    assert is_tool_allowed_in_mode("kicad_get_version", OperatingMode.READONLY) is True
    assert tool_required_mode("pcb_placement_quality_gate") is OperatingMode.READONLY
    assert is_tool_allowed_in_mode("pcb_placement_quality_gate", OperatingMode.READONLY) is True
    assert tool_required_mode("pcb_placement_quality_report") is OperatingMode.READONLY

    assert tool_required_mode("pcb_add_track") is OperatingMode.WRITE
    assert is_tool_allowed_in_mode("pcb_add_track", OperatingMode.READONLY) is False
    assert tool_required_mode("pcb_place_component") is OperatingMode.WRITE
    assert is_tool_allowed_in_mode("pcb_place_component", OperatingMode.READONLY) is False
    assert is_tool_allowed_in_mode("pcb_add_track", OperatingMode.WRITE) is True
    assert is_tool_allowed_in_mode("pcb_add_track", OperatingMode.MANUFACTURING) is False

    assert tool_required_mode("export_manufacturing_package") is OperatingMode.MANUFACTURING
    assert is_tool_allowed_in_mode("export_manufacturing_package", OperatingMode.WRITE) is False
    assert (
        is_tool_allowed_in_mode("export_manufacturing_package", OperatingMode.MANUFACTURING) is True
    )

    assert tool_required_mode("route_tune_length") is OperatingMode.EXPERIMENTAL
    assert is_tool_allowed_in_mode("route_tune_length", OperatingMode.WRITE) is False
    assert is_tool_allowed_in_mode("route_tune_length", OperatingMode.EXPERIMENTAL) is True


def test_default_readonly_mode_filters_mutating_and_high_risk_tools(sample_project) -> None:
    _ = sample_project

    tool_names = _tool_names_for_mode("readonly")

    assert {
        "kicad_get_version",
        "run_drc",
        "run_erc",
        "export_bom",
        "sch_get_symbols",
    } <= tool_names
    assert "pcb_add_track" not in tool_names
    assert "sch_add_symbol" not in tool_names
    assert "export_manufacturing_package" not in tool_names
    assert "route_single_track" not in tool_names
    assert "sch_swap_pins" not in tool_names


def test_write_mode_allows_controlled_source_changes(sample_project) -> None:
    _ = sample_project

    tool_names = _tool_names_for_mode("write")

    assert {"kicad_get_version", "pcb_add_track", "pcb_save", "sch_add_symbol"} <= tool_names
    assert "export_manufacturing_package" not in tool_names
    assert "route_tune_length" not in tool_names
    assert "sch_swap_pins" not in tool_names


def test_manufacturing_mode_exposes_release_exports_without_general_write_tools(
    sample_project,
) -> None:
    _ = sample_project

    tool_names = _tool_names_for_mode("manufacturing")

    assert {
        "kicad_get_version",
        "export_gerber",
        "export_bom",
        "export_manufacturing_package",
        "mfg_generate_release_manifest",
    } <= tool_names
    assert "pcb_add_track" not in tool_names
    assert "sch_add_symbol" not in tool_names
    assert "route_tune_length" not in tool_names


def test_experimental_mode_requires_explicit_opt_in_for_routing_and_unstable_tools(
    sample_project,
) -> None:
    _ = sample_project

    tool_names = _tool_names_for_mode("experimental")

    assert {
        "pcb_add_track",
        "export_manufacturing_package",
        "route_single_track",
        "route_tune_length",
        "sch_swap_pins",
    } <= tool_names


@pytest.mark.anyio
async def test_project_info_reports_effective_experimental_mode(
    monkeypatch,
    sample_project,
) -> None:
    monkeypatch.setenv("KICAD_MCP_OPERATING_MODE", "experimental")
    monkeypatch.delenv("KICAD_MCP_ENABLE_EXPERIMENTAL_TOOLS", raising=False)
    reset_config()
    server = build_server("full")

    text = await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    expected = "- " + "Experimental tools: True"
    assert expected in text


@pytest.mark.anyio
async def test_experimental_mode_enables_legacy_experimental_pcb_guards(monkeypatch) -> None:
    monkeypatch.setenv("KICAD_MCP_OPERATING_MODE", "experimental")
    monkeypatch.delenv("KICAD_MCP_ENABLE_EXPERIMENTAL_TOOLS", raising=False)
    reset_config()
    server = build_server("full")

    text = await call_tool_text(server, "pcb_highlight_net", {"net_name": "GND"})

    assert "Enable experimental tools" not in text
    assert "Net highlighting is not exposed as a stable" in text


@pytest.mark.anyio
async def test_readonly_mode_rejects_write_tool_execution(monkeypatch) -> None:
    monkeypatch.setenv("KICAD_MCP_OPERATING_MODE", "readonly")
    reset_config()
    server = KiCadFastMCP(name="kicad-mcp-pro-test")
    called = False

    @server.tool(name="pcb_add_track")
    def pcb_add_track() -> str:
        nonlocal called
        called = True
        return "mutated"

    result = await server.call_tool("pcb_add_track", {})

    assert called is False
    assert result.isError is True
    assert result.structuredContent is None
    assert len(result.content) == 1
    text = result.content[0].text
    assert "MODE_FORBIDDEN" in text
    assert "pcb_add_track" in text
    assert "write operating mode" in text
    assert "--mode write" in text


def test_experimental_cli_flag_is_explicit_mode_opt_in(monkeypatch) -> None:
    monkeypatch.delenv("KICAD_MCP_OPERATING_MODE", raising=False)
    monkeypatch.delenv("KICAD_MCP_ENABLE_EXPERIMENTAL_TOOLS", raising=False)

    _apply_cli_env(experimental=True)

    assert os.environ["KICAD_MCP_ENABLE_EXPERIMENTAL_TOOLS"] == "true"
    assert os.environ["KICAD_MCP_OPERATING_MODE"] == "experimental"

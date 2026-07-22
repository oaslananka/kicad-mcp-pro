from __future__ import annotations

import json
from pathlib import Path

from kicad_mcp.adapter_matrix import (
    CATEGORY_ADAPTER_POLICIES,
    AdapterBackend,
    AdapterRuntimeContext,
    adapter_routing_contract,
    build_adapter_matrix_payload,
    decision_for_tool,
)
from kicad_mcp.tools.router import TOOL_CATEGORIES

ROOT = Path(__file__).resolve().parents[2]
GENERATED_JSON = ROOT / "integrations" / "common" / "kicad-adapter-matrix.json"
GENERATED_DOCS = ROOT / "docs" / "compatibility" / "kicad-adapter-matrix.generated.md"


def _kicad11_context() -> AdapterRuntimeContext:
    return AdapterRuntimeContext(
        kicad_major=11,
        ipc_reachable=True,
        live_pcb_context=False,
        live_schematic_context=False,
        headless_ipc_available=True,
        cli_available=True,
        ngspice_available=True,
        freerouting_available=True,
        docker_available=True,
        network_available=True,
    )


def test_adapter_policies_cover_every_routed_tool_category() -> None:
    assert set(CATEGORY_ADAPTER_POLICIES) == set(TOOL_CATEGORIES)


def test_generated_matrix_covers_every_routed_tool_exactly_once() -> None:
    payload = build_adapter_matrix_payload()
    routed_tools = {
        tool_name for detail in TOOL_CATEGORIES.values() for tool_name in detail["tools"]
    }
    matrix_tools = {row["tool"] for row in payload["tools"]}

    assert matrix_tools == routed_tools
    assert len(payload["tools"]) == len(routed_tools)
    assert payload["summary"]["categoryCount"] == len(TOOL_CATEGORIES)
    assert payload["summary"]["toolCount"] == len(routed_tools)


def test_kicad11_prefers_headless_ipc_for_live_pcb_and_schematic_tools() -> None:
    context = _kicad11_context()

    pcb = decision_for_tool("pcb_route_trace", context)
    schematic = decision_for_tool("sch_reload", context)

    assert pcb.backend is AdapterBackend.KICAD_11_HEADLESS_IPC
    assert schematic.backend is AdapterBackend.KICAD_11_HEADLESS_IPC
    assert pcb.available is True
    assert schematic.available is True


def test_kicad11_gui_ipc_is_not_mislabeled_as_headless() -> None:
    context = AdapterRuntimeContext(
        kicad_major=11,
        ipc_reachable=True,
        live_pcb_context=True,
        live_schematic_context=True,
        headless_ipc_available=False,
        cli_available=True,
    )

    decision = decision_for_tool("pcb_route_trace", context)

    assert decision.backend is AdapterBackend.KICAD_GUI_IPC
    assert decision.available is True


def test_kicad10_requires_live_document_context_for_ipc_routes() -> None:
    without_board = AdapterRuntimeContext(
        kicad_major=10,
        ipc_reachable=True,
        live_pcb_context=False,
        live_schematic_context=False,
        cli_available=True,
    )
    with_board = AdapterRuntimeContext(
        kicad_major=10,
        ipc_reachable=True,
        live_pcb_context=True,
        live_schematic_context=True,
        cli_available=True,
    )

    blocked = decision_for_tool("pcb_route_trace", without_board)
    available = decision_for_tool("pcb_route_trace", with_board)

    assert blocked.backend is AdapterBackend.UNAVAILABLE
    assert blocked.available is False
    assert available.backend is AdapterBackend.KICAD_GUI_IPC
    assert available.available is True


def test_cli_exports_and_guarded_file_mutations_have_deterministic_routes() -> None:
    context = _kicad11_context()

    export = decision_for_tool("export_gerber", context)
    schematic_file_write = decision_for_tool("sch_add_component", context)
    local_analysis = decision_for_tool("dfm_run_manufacturer_check", context)

    assert export.backend is AdapterBackend.KICAD_CLI
    assert export.mutation_guard == "isolated-output-validation"
    assert schematic_file_write.backend is AdapterBackend.GUARDED_SCHEMATIC_FILE
    assert schematic_file_write.mutation_guard == "atomic-roundtrip-loss-detection"
    assert local_analysis.backend is AdapterBackend.LOCAL_ENGINE


def test_active_routing_contract_is_compact_and_observable() -> None:
    contract = adapter_routing_contract(_kicad11_context())

    assert contract["schemaVersion"] == "1.0.0"
    assert contract["context"]["kicadMajor"] == 11
    assert set(contract["categories"]) == set(TOOL_CATEGORIES)
    assert contract["categories"]["pcb_write"]["selectedBackends"]["kicad-11-headless-ipc"]
    assert contract["categories"]["export"]["selectedBackends"]["kicad-cli"]


def test_generated_adapter_artifacts_match_runtime_payload() -> None:
    payload = json.loads(GENERATED_JSON.read_text(encoding="utf-8"))

    assert payload == build_adapter_matrix_payload()
    assert "# KiCad Adapter Matrix" in GENERATED_DOCS.read_text(encoding="utf-8")

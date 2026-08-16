from __future__ import annotations

from kicad_mcp.capabilities import (
    AccessTier,
    RuntimeRequirement,
    all_records,
    get,
    is_allowed,
    tools_for_profile,
)

REQUIRED_OASLANA_119_TOOLS = {
    "pcb_place_component",
    "pcb_route_trace",
    "pcb_add_zone",
    "pcb_set_design_rules",
    "pcb_move_component",
    "pcb_delete_object",
    "sch_add_component",
    "sch_add_wire",
    "sch_modify_property",
}


def test_is_allowed_for_known_tools_and_profiles() -> None:
    assert is_allowed("kicad_set_project", "minimal") is True
    assert is_allowed("sch_add_symbol", "schematic_only") is True
    assert is_allowed("sch_add_symbol", "minimal") is False
    assert is_allowed("pcb_add_track", "pcb_only") is True
    assert is_allowed("missing_tool", "agent_full") is False


def test_minimal_profile_has_expected_core_tools() -> None:
    records = tools_for_profile("minimal")

    assert records
    names = {record.name for record in records}
    assert {
        "kicad_set_project",
        "kicad_health",
        "kicad_doctor",
        "kicad_get_project_info",
        "pcb_get_board_summary",
        "export_gerber",
    }.issubset(names)
    # Minimal profile can include non-read tiers, but should remain compact.
    assert len(records) < 100


def test_manufacturing_package_requires_human_gate() -> None:
    record = get("export_manufacturing_package")

    assert record is not None
    assert record.human_gate_required is True
    assert record.tier == AccessTier.HUMAN_ONLY
    assert record.supports_dry_run is True


def test_registered_tools_have_valid_verification_levels() -> None:
    valid_levels = {"verified", "experimental", "planned"}

    assert all_records()
    for record in all_records().values():
        assert record.verification_level in valid_levels


def test_contract_side_effect_flags_are_consistent_with_access_tier() -> None:
    """Contract invariants (#196): the side-effect flags an agent reads to decide
    whether a call is safe must never contradict the access tier."""
    for record in all_records().values():
        if record.tier is AccessTier.READ:
            assert record.writes_files is False, record.name
            assert record.writes_kicad_gui_state is False, record.name
        if record.tier is AccessTier.HUMAN_ONLY:
            assert record.human_gate_required is True, record.name
        if record.human_gate_required:
            assert record.tier is AccessTier.HUMAN_ONLY, record.name


def test_oaslana_119_pcb_live_editing_tools_require_kicad_ipc() -> None:
    records = all_records()
    pcb_tools = {name for name in REQUIRED_OASLANA_119_TOOLS if name.startswith("pcb_")}

    assert pcb_tools.issubset(records)
    for tool_name in pcb_tools:
        record = records[tool_name]
        assert record.runtime is RuntimeRequirement.KICAD_IPC
        assert record.tier is AccessTier.WRITE


def test_file_backed_schematic_authoring_tools_do_not_require_live_kicad_ipc() -> None:
    records = all_records()
    schematic_tools = {name for name in REQUIRED_OASLANA_119_TOOLS if name.startswith("sch_")} | {
        "sch_add_symbol",
        "sch_add_label",
        "sch_update_properties",
        "sch_build_circuit",
        "sch_annotate",
    }

    assert schematic_tools.issubset(records)
    for tool_name in schematic_tools:
        record = records[tool_name]
        assert record.runtime is RuntimeRequirement.NONE
        assert record.tier is AccessTier.WRITE
        assert record.writes_files is True


def test_file_backed_schematic_category_tools_do_not_require_live_ipc() -> None:
    records = all_records()
    file_backed = {
        "sch_create_sheet",
        "sch_add_pin_labels",
        "sch_live_preview",
        "sch_delete_no_connect",
        "variant_create",
    }

    assert file_backed.issubset(records)
    for tool_name in file_backed:
        record = records[tool_name]
        assert record.runtime is RuntimeRequirement.NONE, tool_name
        assert record.writes_files is True, tool_name
        assert record.writes_kicad_gui_state is False, tool_name


def test_sch_reload_remains_live_ipc_only() -> None:
    record = get("sch_reload")

    assert record is not None
    assert record.runtime is RuntimeRequirement.KICAD_IPC
    assert record.writes_kicad_gui_state is True


def test_profile_results_are_copies() -> None:
    records = all_records()
    records.clear()

    assert all_records()

"""Tool routing, metadata labels, and server profiles."""

from __future__ import annotations

from typing import TypedDict

from mcp.server.fastmcp import FastMCP

from .metadata import get_tool_metadata


class ToolCategory(TypedDict):
    """Router metadata for a single tool category."""

    description: str
    tools: list[str]


EXPERIMENTAL_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "sch_swap_pins",
        "sch_swap_gates",
        "sch_add_jumper",
        "sch_reload",
    }
)


def _display_tool_name(tool_name: str) -> str:
    suffixes: list[str] = []
    if tool_name in EXPERIMENTAL_TOOL_NAMES:
        suffixes.append("EXPERIMENTAL")
    try:
        from ..capabilities import get as get_capability

        capability = get_capability(tool_name)
    except Exception:
        capability = None
    if capability is not None:
        suffixes.append(f"MATURITY:{capability.maturity.value}")
    metadata = get_tool_metadata(tool_name)
    if metadata is not None:
        if metadata.headless_compatible:
            suffixes.append("HEADLESS")
        if metadata.requires_kicad_running:
            suffixes.append("REQUIRES_KICAD")
        for dependency in metadata.dependencies:
            suffixes.append(f"REQUIRES:{dependency}")
    if not suffixes:
        return tool_name
    return f"{tool_name} [{' / '.join(suffixes)}]"


def _mode_availability_note(tool_name: str) -> str:
    try:
        from ..operating_modes import active_operating_mode, tool_availability

        active = active_operating_mode()
        availability = tool_availability(tool_name, active)
    except Exception:
        return ""
    if availability.available:
        return ""
    return (
        f" — unavailable in `{active.value}` mode; "
        f"requires `{availability.required_mode.value}` mode"
    )


def _tool_requires_kicad_ipc(tool_name: str) -> bool:
    try:
        from ..capabilities import RuntimeRequirement
        from ..capabilities import get as get_capability

        capability = get_capability(tool_name)
    except Exception:
        return False
    return bool(capability and capability.runtime is RuntimeRequirement.KICAD_IPC)


def _runtime_availability_note(tool_name: str, ipc_state: object | None) -> str:
    if ipc_state is None or not _tool_requires_kicad_ipc(tool_name):
        return ""
    try:
        from ..capabilities import AccessTier
        from ..capabilities import get as get_capability

        capability = get_capability(tool_name)
    except Exception:
        return ""
    tier = capability.tier if capability is not None else AccessTier.WRITE

    operations = getattr(ipc_state, "operations", {})
    if tool_name in operations:
        operation = operations[tool_name]
        if getattr(operation, "available", False):
            return ""
        reason = getattr(operation, "reason", None)
        return " — unavailable at runtime; " + (
            str(reason) if reason else "KiCad IPC operation is unavailable"
        )

    if tool_name.startswith("pcb_"):
        available = (
            getattr(ipc_state, "live_pcb_read", False)
            if tier is AccessTier.READ
            else getattr(ipc_state, "live_pcb_write", False)
        )
        requirement = "live PCB read" if tier is AccessTier.READ else "live PCB write"
    elif tool_name.startswith("sch_"):
        available = (
            getattr(ipc_state, "live_schematic_read", False)
            if tier is AccessTier.READ
            else getattr(ipc_state, "live_schematic_write", False)
        )
        requirement = "live schematic read" if tier is AccessTier.READ else "live schematic write"
    else:
        available = getattr(ipc_state, "reachable", False)
        requirement = "KiCad IPC connection"

    if available:
        return ""
    return f" — unavailable at runtime; requires {requirement}"


TOOL_CATEGORIES: dict[str, ToolCategory] = {
    "project": {
        "description": "Project setup, server discovery, and quick help.",
        "tools": [
            "kicad_set_project",
            "kicad_get_project_info",
            "project_design_workflow",
            "project_set_design_intent",
            "project_import_design_spec",
            "project_get_design_intent",
            "project_get_design_spec",
            "project_infer_design_spec",
            "project_assess_edit_impact",
            "project_revalidate_after_edit",
            "project_validate_design_spec",
            "project_generate_design_prompt",
            "project_get_next_action",
            "project_auto_fix_loop",
            "project_full_validation_loop",
            "project_gate_trend",
            "project_design_report",
            "kicad_list_recent_projects",
            "kicad_scan_directory",
            "kicad_create_new_project",
            "kicad_get_version",
            "kicad_get_server_info",
            "kicad_list_tool_categories",
            "kicad_get_tools_in_category",
            "kicad_capability_parity",
            "kicad_help",
            "studio_push_context",
            # v3.8.0 — embedded file management
            "project_list_embedded_files",
            "project_embed_file",
            "project_extract_embedded_file",
            "project_remove_embedded_file",
        ],
    },
    "pcb_read": {
        "description": "Read PCB state including tracks, vias, footprints, nets, and layers.",
        "tools": [
            "pcb_get_board_summary",
            "pcb_get_tracks",
            "pcb_get_vias",
            "pcb_get_footprints",
            "pcb_get_nets",
            "pcb_get_zones",
            "pcb_get_shapes",
            "pcb_get_pads",
            "pcb_get_layers",
            "pcb_get_stackup",
            "pcb_get_selection",
            "pcb_get_board_as_string",
            "pcb_get_ratsnest",
            "pcb_get_design_rules",
            "pcb_get_footprint_layers",
            "pcb_visual_qa",
            "pcb_get_impedance_for_trace",
            "pcb_get_groups",
            "pcb_get_origin",
            "pcb_check_creepage_clearance",
            "pcb_block_list",
            # v3.8.0 — net analysis
            "pcb_get_net_statistics",
            "pcb_net_inspector",
            # v3.8.0 — test point tools
            "pcb_add_test_point",
            "pcb_list_test_points",
            "pcb_optimize_test_point_placement",
            "pcb_check_test_coverage",
        ],
    },
    "pcb_write": {
        "description": "Modify PCB geometry, sync initial footprints, and save board changes.",
        "tools": [
            "pcb_add_track",
            "pcb_route_trace",
            "pcb_add_tracks_bulk",
            "pcb_add_via",
            "pcb_add_zone",
            "pcb_add_copper_zone",
            "pcb_add_segment",
            "pcb_add_circle",
            "pcb_add_rectangle",
            "pcb_add_text",
            "pcb_set_board_outline",
            "pcb_set_design_rules",
            "pcb_set_stackup",
            "pcb_add_blind_via",
            "pcb_add_microvia",
            "pcb_auto_place_by_schematic",
            "pcb_place_decoupling_caps",
            "pcb_group_by_function",
            "pcb_align_footprints",
            "pcb_set_keepout_zone",
            "pcb_add_mounting_holes",
            "pcb_add_fiducial_marks",
            "pcb_add_teardrops",
            "pcb_auto_place_force_directed",
            "pcb_bga_fanout",
            "pcb_delete_object",
            "pcb_delete_items",
            "pcb_save",
            "pcb_refill_zones",
            "pcb_highlight_net",
            "pcb_set_net_class",
            "pcb_place_component",
            "pcb_move_component",
            "pcb_move_footprint",
            "pcb_set_footprint_layer",
            "pcb_sync_from_schematic",
            "pcb_set_origin",
            "pcb_set_title_block_info",
            "pcb_import_board",
            "pcb_begin_commit",
            "pcb_push_commit",
            "pcb_drop_commit",
            "pcb_revert",
            "add_footprint_inner_layer_graphic",
            "pcb_add_barcode",
            "pcb_add_bitmap_board_art",
            "pcb_block_create_from_selection",
            "pcb_block_place",
        ],
    },
    "schematic": {
        "description": "Inspect and edit schematic files with hybrid IPC reload support.",
        "tools": [
            "sch_get_symbols",
            "sch_get_wires",
            "sch_get_labels",
            "sch_get_net_names",
            "sch_create_sheet",
            "sch_list_sheets",
            "sch_get_sheet_info",
            "sch_list_sheet_pins",
            "sch_add_symbol",
            "sch_add_component",
            "sch_add_wire",
            "sch_add_label",
            "sch_add_labels",
            "sch_add_pin_labels",
            "sch_add_global_label",
            "sch_add_hierarchical_label",
            "sch_add_sheet_pin",
            "sch_import_sheet_pins",
            "sch_spread_sheets",
            "sch_wire_sheet_pins",
            "sch_add_power_symbol",
            "sch_add_bus",
            "sch_add_bus_wire_entry",
            "sch_add_no_connect",
            "sch_set_dnp",
            "sch_get_population_status",
            "sch_update_properties",
            "sch_modify_property",
            "sch_delete_symbol",
            "sch_move_symbol",
            "sch_delete_wire",
            "sch_delete_label",
            "sch_delete_no_connect",
            "sch_move_label",
            "sch_modify_label",
            "sch_analyze_net_compilation",
            "sch_build_circuit",
            "sch_get_pin_positions",
            "sch_route_wire_between_pins",
            "sch_add_missing_junctions",
            "sch_get_connectivity_graph",
            "sch_trace_net",
            "sch_auto_place_symbols",
            "sch_autoplace_fields",
            "sch_fix_readability",
            "sch_check_power_flags",
            "sch_annotate",
            "sch_reload",
            # v2.1.0 — spatial awareness + sheet size tools
            "sch_get_bounding_boxes",
            "sch_find_free_placement",
            "sch_auto_place_functional",
            "sch_render_png",
            "sch_render_visual_diff",
            "sch_live_preview",
            "sch_get_circuit_ir",
            "sch_visual_qa",
            "sch_cosmetic_score",
            "sch_align_to_grid",
            "sch_straighten_wires",
            "sch_resolve_label_overlaps",
            "sch_normalize_power_orientation",
            "sch_normalize_text_sizes",
            "sch_visual_baseline_set",
            "sch_visual_baseline_compare",
            "sch_plan_from_spec",
            "sch_preview_plan",
            "sch_apply_plan",
            "sch_verify_plan",
            "sch_rollback_plan",
            "sch_set_title_block_info",
            "sch_set_sheet_size",
            "sch_auto_resize_sheet",
            # v2.1.0 — subcircuit template tools
            "sch_list_templates",
            "sch_get_template_info",
            "sch_instantiate_template",
            "sch_set_hop_over",
            "sch_list_swappable_pins",
            "sch_swap_pins",
            "sch_swap_gates",
            "sch_add_jumper",
            "variant_list",
            "variant_create",
            "variant_set_active",
            "variant_set_component_override",
            "variant_diff_bom",
            "variant_export_bom",
            # v3.8.0 — variant extended
            "variant_clone",
            "variant_delete",
            "variant_get_component_status",
            "variant_export_schematic",
            "variant_export_manufacturing_package",
        ],
    },
    "library": {
        "description": "Search and inspect symbol/footprint libraries plus live component data.",
        "tools": [
            "lib_search_symbols",
            "lib_get_symbol_info",
            "lib_list_libraries",
            "lib_search_footprints",
            "lib_list_footprints",
            "lib_rebuild_index",
            "lib_get_footprint_info",
            "lib_get_footprint_3d_model",
            "lib_verify_component_contract",
            "lib_assign_footprint",
            "lib_create_custom_symbol",
            "lib_search_components",
            "lib_get_component_details",
            "lib_assign_lcsc_to_symbol",
            "lib_get_bom_with_pricing",
            "lib_check_stock_availability",
            "lib_check_sourcing_policy",
            "lib_find_alternative_parts",
            "lib_get_datasheet_url",
            # v2.2.0 — generative library tools
            "lib_generate_footprint_ipc7351",
            "lib_validate_footprint_ipc7351",
            "lib_certify_footprint",
            "lib_check_derating",
            "lib_generate_symbol_from_pintable",
            "lib_recommend_part",
            "lib_bind_part_to_symbol",
            # v3.8.0 — 3D model management
            "lib_set_3d_model_path",
            "lib_remove_3d_model",
            "lib_bulk_assign_3d_models",
            "lib_search_3d_models",
        ],
    },
    "export": {
        "description": "Produce low-level debug, review, and interchange exports.",
        "tools": [
            "export_gerber",
            "export_drill",
            "export_bom",
            "export_netlist",
            "export_spice_netlist",
            "export_pcb_pdf",
            "export_sch_pdf",
            "export_3d_step",
            "export_step",
            "export_stepz",
            "export_xao",
            "export_3d_render",
            "export_pick_and_place",
            "export_ipc2581",
            "export_odb",
            "export_svg",
            "export_dxf",
            "export_sch_svg",
            "export_sch_dxf",
            "export_sch_python_bom",
            "pcb_export_3d_pdf",
            # v2.5.0 — additional PCB export parity formats
            "export_brep",
            "export_glb",
            "export_gencad",
            "export_ipc_d356",
            "export_ply",
            "export_stl",
            "export_u3d",
            "export_vrml",
            "export_ps",
            # v3.8.0 — board stats CLI
            "pcb_export_stats",
        ],
    },
    "release_export": {
        "description": "Produce release-gated manufacturing handoff artifacts.",
        "tools": [
            "export_manufacturing_package",
            "get_board_stats",
        ],
    },
    "manufacturing": {
        "description": "Panelization, bring-up test plan generation, and release manifest.",
        "tools": [
            "mfg_panelize",
            "mfg_generate_test_plan",
            "mfg_generate_release_manifest",
            "mfg_create_release_evidence",
            "mfg_correct_cpl_rotations",
            "mfg_check_import_support",
            "mfg_import_allegro",
            "mfg_import_pads",
            "mfg_import_geda",
            "jobset_list_templates",
            "jobset_export",
            "jobset_run",
            "jobset_validate",
            "fp_export",
            "fp_export_svg",
            "fp_upgrade",
            "fp_get_info",
            "sym_export",
            "sym_export_svg",
            "sym_upgrade",
            "mfg_import_specctra",
            "sch_upgrade",
            "pcb_upgrade",
        ],
    },
    "validation": {
        "description": "Design validation, DFM checks, and rule inspection.",
        "tools": [
            "schematic_quality_gate",
            "schematic_connectivity_gate",
            "schematic_design_rule_check",
            "pcb_quality_gate",
            "pcb_placement_quality_gate",
            "pcb_placement_quality_report",
            "pcb_transfer_quality_gate",
            "pcb_stackup_consistency_gate",
            "pcb_route_corner_style_gate",
            "pcb_score_placement",
            "pcb_critique_placement",
            "manufacturing_quality_gate",
            "project_quality_gate",
            "project_quality_gate_report",
            "project_signoff_report",
            "project_release_readiness",
            "project_professional_release_gate",
            "run_drc",
            "run_erc",
            "validate_design",
            "check_design_for_manufacture",
            "get_unconnected_nets",
            "get_courtyard_violations",
            "get_silk_to_pad_violations",
            "validate_footprints_vs_schematic",
            "drc_list_rules",
            "drc_check_rule_conflicts",
            "drc_rule_create",
            "drc_rule_delete",
            "drc_rule_enable",
            "drc_export_rules",
            # v3.8.0 — DRC exclusion management
            "drc_list_exclusions",
            "drc_add_exclusion",
            "drc_remove_exclusion",
            "drc_validate_exclusions",
            # v3.8.0 — ERC rule severity
            "erc_list_rules",
            "erc_set_rule_severity",
            "erc_reset_rules",
        ],
    },
    "dfm": {
        "description": "Load bundled manufacturer profiles, run DFM checks, and estimate cost.",
        "tools": [
            "dfm_load_manufacturer_profile",
            "dfm_run_manufacturer_check",
            "dfm_calculate_manufacturing_cost",
        ],
    },
    "routing": {
        "description": (
            "Advanced routing helpers including FreeRouting orchestration and rule-file tuning."
        ),
        "tools": [
            "route_single_track",
            "route_from_pad_to_pad",
            "route_export_dsn",
            "route_import_ses",
            "route_apply_ses",
            "route_autoroute_freerouting",
            "route_set_net_class_rules",
            "route_differential_pair",
            "route_tune_length",
            "tune_diff_pair_length",
            "route_create_tuning_profile",
            "route_list_tuning_profiles",
            "route_apply_tuning_profile",
            "route_tune_time_domain",
            "generate_board_constraints",
        ],
    },
    "signal_integrity": {
        "description": (
            "Estimate impedance, skew, length matching, stackup geometry, via stubs, "
            "and decoupling placement."
        ),
        "tools": [
            "si_get_solver_capabilities",
            "si_calculate_trace_impedance",
            "si_calculate_trace_width_for_impedance",
            "si_check_differential_pair_skew",
            "si_validate_length_matching",
            "si_generate_stackup",
            "si_check_via_stub",
            "si_calculate_decoupling_placement",
            # v2.3.0 — stackup synthesis + net class binding
            "si_list_dielectric_materials",
            "si_synthesize_stackup_for_interfaces",
            "si_bind_interfaces_to_net_classes",
            # P3-T3 — high-speed channel insertion-loss / eye analysis
            "si_analyze_high_speed_channel",
        ],
    },
    "power_integrity": {
        "description": (
            "Estimate voltage drop, current capacity, decoupling needs, power planes, "
            "and thermal spreading."
        ),
        "tools": [
            "check_power_integrity",
            "pdn_calculate_voltage_drop",
            "pdn_recommend_decoupling_caps",
            "pdn_check_copper_weight",
            "pdn_generate_power_plane",
            "thermal_calculate_via_count",
            "thermal_check_copper_pour",
            # P3-T4 — 2-D finite-difference copper-plane thermal spreading solver
            "thermal_simulate_plane_spreading",
        ],
    },
    "emc": {
        "description": "Run lightweight EMC-oriented layout checks and a bundled compliance sweep.",
        "tools": [
            "emc_check_ground_plane_voids",
            "emc_check_return_path_continuity",
            "emc_check_split_plane_crossing",
            "emc_check_decoupling_placement",
            "emc_check_via_stitching",
            "emc_check_differential_pair_symmetry",
            "emc_check_high_speed_routing_rules",
            "emc_run_full_compliance",
        ],
    },
    "simulation": {
        "description": "SPICE analysis, model assignment, and library management.",
        "tools": [
            "sim_run_operating_point",
            "sim_run_ac_analysis",
            "sim_run_transient",
            "sim_run_dc_sweep",
            "sim_check_stability",
            "sim_add_spice_directive",
            "sim_assign_spice_model",
            "sim_list_spice_libraries",
            "sim_add_spice_library",
            "sim_remove_spice_library",
            "sim_validate_spice_setup",
        ],
    },
    "version_control": {
        "description": "Create Git checkpoints, inspect diffs, and safely restore project files.",
        "tools": [
            "vcs_init_git",
            "vcs_commit_checkpoint",
            "vcs_list_checkpoints",
            "vcs_restore_checkpoint",
            "vcs_diff_with_checkpoint",
            "vcs_tag_release",
        ],
    },
}

# Progressive-disclosure profiles intentionally use exact tool allowlists rather
# than whole categories. Categories remain the registration/composition boundary,
# while these lists are the public discovery boundary exposed to general agents.
# Keep each workflow surface small enough for reliable tool selection; advanced
# clients can opt into ``expert`` or ``full`` without losing any tools.
_REVIEW_TOOLS: tuple[str, ...] = (
    "kicad_set_project",
    "kicad_get_project_info",
    "kicad_get_version",
    "kicad_get_server_info",
    "kicad_list_tool_categories",
    "kicad_get_tools_in_category",
    "project_get_next_action",
    "project_design_workflow",
    "pcb_get_board_summary",
    "pcb_get_design_rules",
    "pcb_get_stackup",
    "sch_get_symbols",
    "sch_get_connectivity_graph",
    "sch_get_bounding_boxes",
    "validate_design",
    "run_drc",
    "run_erc",
    "validate_footprints_vs_schematic",
    "pcb_visual_qa",
    "dfm_run_manufacturer_check",
    "project_quality_gate",
    "lib_verify_component_contract",
    "sch_visual_qa",
    "lib_get_bom_with_pricing",
)

_BUILD_TOOLS: tuple[str, ...] = (
    "kicad_set_project",
    "kicad_get_project_info",
    "kicad_list_tool_categories",
    "kicad_get_tools_in_category",
    "project_design_workflow",
    "project_get_design_spec",
    "project_assess_edit_impact",
    "sch_plan_from_spec",
    "sch_preview_plan",
    "sch_apply_plan",
    "sch_verify_plan",
    "sch_rollback_plan",
    "pcb_get_tracks",
    "pcb_get_vias",
    "pcb_begin_commit",
    "pcb_delete_items",
    "pcb_delete_object",
    "pcb_push_commit",
    "pcb_drop_commit",
    "pcb_revert",
    "run_drc",
    "project_quality_gate",
    "vcs_commit_checkpoint",
    "vcs_diff_with_checkpoint",
)

_RELEASE_TOOLS: tuple[str, ...] = (
    "kicad_set_project",
    "kicad_get_project_info",
    "kicad_get_version",
    "kicad_get_server_info",
    "kicad_list_tool_categories",
    "kicad_get_tools_in_category",
    "project_get_next_action",
    "project_get_design_spec",
    "project_validate_design_spec",
    "pcb_get_board_summary",
    "pcb_get_design_rules",
    "pcb_get_stackup",
    "validate_design",
    "run_drc",
    "run_erc",
    "validate_footprints_vs_schematic",
    "check_design_for_manufacture",
    "dfm_run_manufacturer_check",
    "project_quality_gate",
    "manufacturing_quality_gate",
    "get_board_stats",
    "export_manufacturing_package",
    "vcs_list_checkpoints",
    "vcs_diff_with_checkpoint",
)

PROFILE_TOOL_ALLOWLISTS: dict[str, tuple[str, ...]] = {
    "default": _REVIEW_TOOLS,
    "review": _REVIEW_TOOLS,
    "build": _BUILD_TOOLS,
    "release": _RELEASE_TOOLS,
}


def _categories_for_tools(tools: tuple[str, ...]) -> tuple[str, ...]:
    selected = set(tools)
    return tuple(
        category
        for category, info in TOOL_CATEGORIES.items()
        if selected.intersection(info["tools"])
    )


PROFILE_CATEGORIES: dict[str, tuple[str, ...]] = {
    "full": tuple(TOOL_CATEGORIES.keys()),
    "expert": tuple(TOOL_CATEGORIES.keys()),
    "default": _categories_for_tools(_REVIEW_TOOLS),
    "review": _categories_for_tools(_REVIEW_TOOLS),
    "build": _categories_for_tools(_BUILD_TOOLS),
    "release": _categories_for_tools(_RELEASE_TOOLS),
    "minimal": ("project", "pcb_read", "export"),
    "beginner": ("project", "pcb_read", "dfm"),
    "read_only_inspection": ("project", "pcb_read", "dfm"),
    "schematic_only": ("project", "schematic", "library"),
    "schematic_authoring": ("project", "schematic", "library", "validation", "version_control"),
    "pcb_only": ("project", "pcb_read", "pcb_write", "routing"),
    "pcb_layout": ("project", "pcb_read", "pcb_write", "routing", "validation", "version_control"),
    "manufacturing": (
        "project",
        "pcb_read",
        "release_export",
        "validation",
        "dfm",
        "manufacturing",
    ),
    "manufacturing_release": (
        "project",
        "pcb_read",
        "release_export",
        "validation",
        "dfm",
        "manufacturing",
        "version_control",
    ),
    "builder": (
        "project",
        "schematic",
        "library",
        "pcb_read",
        "pcb_write",
        "routing",
        "validation",
        "version_control",
    ),
    "critic": (
        "project",
        "schematic",
        "pcb_read",
        "validation",
        "dfm",
        "signal_integrity",
        "power_integrity",
        "emc",
    ),
    "release_manager": (
        "project",
        "pcb_read",
        "validation",
        "dfm",
        "release_export",
        "version_control",
    ),
    "high_speed": (
        "project",
        "schematic",
        "pcb_read",
        "pcb_write",
        "routing",
        "signal_integrity",
        "emc",
        "validation",
        "export",
        "simulation",
        "version_control",
    ),
    "power": (
        "project",
        "schematic",
        "pcb_read",
        "pcb_write",
        "power_integrity",
        "validation",
        "export",
    ),
    "simulation": ("project", "schematic", "simulation", "export", "library"),
    "analysis": ("project", "pcb_read", "signal_integrity", "power_integrity", "emc", "validation"),
    "agent_full": tuple(TOOL_CATEGORIES.keys()),
    # Backward-compatible aliases kept for existing clients.
    "pcb": ("project", "pcb_read", "pcb_write", "routing", "export", "validation"),
    "schematic": ("project", "schematic", "library", "export", "validation"),
}


def _category_by_tool() -> dict[str, str]:
    return {
        tool_name: category
        for category, info in TOOL_CATEGORIES.items()
        for tool_name in info["tools"]
    }


def categories_for_profile(profile: str) -> tuple[str, ...]:
    """Resolve registration categories enabled by a named server profile.

    Unknown names fail closed to the bounded default profile instead of silently
    exposing the complete expert catalog.
    """
    selected = profile if profile in PROFILE_CATEGORIES else "default"
    explicit_tools = PROFILE_TOOL_ALLOWLISTS.get(selected)
    if explicit_tools is None:
        return PROFILE_CATEGORIES[selected]
    tool_categories = {_category_by_tool()[tool_name] for tool_name in explicit_tools}
    return tuple(category for category in TOOL_CATEGORIES if category in tool_categories)


def tools_for_profile(profile: str) -> tuple[str, ...]:
    """Return unique tool names enabled by a server profile, preserving order."""
    selected = profile if profile in PROFILE_CATEGORIES else "default"
    explicit_tools = PROFILE_TOOL_ALLOWLISTS.get(selected)
    if explicit_tools is not None:
        return explicit_tools

    seen: set[str] = set()
    tools: list[str] = []
    for category in categories_for_profile(selected):
        for tool_name in TOOL_CATEGORIES[category]["tools"]:
            if tool_name not in seen:
                seen.add(tool_name)
                tools.append(tool_name)
    return tuple(tools)


def tool_count_for_profile(profile: str) -> int:
    """Return the unique public tool count enabled by a server profile."""
    return len(tools_for_profile(profile))


def available_profiles() -> tuple[str, ...]:
    """Return the supported server profile names."""
    preferred = [
        "default",
        "review",
        "build",
        "release",
        "expert",
        "full",
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
    ]
    return tuple(name for name in preferred if name in PROFILE_CATEGORIES)


def register(mcp: FastMCP) -> None:
    """Register category discovery tools."""

    def visible_tools(category: str) -> tuple[str, ...]:
        info = TOOL_CATEGORIES[category]
        allowed = getattr(mcp, "allowed_tool_names", None)
        if not isinstance(allowed, (set, frozenset)):
            return tuple(info["tools"])
        return tuple(tool_name for tool_name in info["tools"] if tool_name in allowed)

    @mcp.tool()
    def kicad_list_tool_categories() -> str:
        """List all available tool categories and capabilities."""
        lines = ["# KiCad MCP Pro Tool Categories", ""]
        for category, info in TOOL_CATEGORIES.items():
            tools = visible_tools(category)
            if not tools:
                continue
            lines.append(f"## `{category}`")
            lines.append(str(info["description"]))
            lines.append(f"Tools: {len(tools)}")
            lines.append("")
        lines.append("Profiles:")
        lines.extend(f"- `{profile}`" for profile in available_profiles())
        return "\n".join(lines)

    @mcp.tool()
    def kicad_get_tools_in_category(category: str, maturity: str = "") -> str:
        """Get tool names in a category, optionally filtered by maturity."""
        info = TOOL_CATEGORIES.get(category)
        tools = visible_tools(category) if info is not None else ()
        if info is None or not tools:
            available = ", ".join(sorted(name for name in TOOL_CATEGORIES if visible_tools(name)))
            return (
                f"Unknown or unavailable category '{category}'. Available categories: {available}"
            )

        from ..operating_modes import active_operating_mode

        active_mode = active_operating_mode()
        try:
            from ..config import get_config
            from ..ipc.capabilities import get_ipc_capability_state

            runtime_filter_enabled = bool(get_config().filter_runtime_tools)
            ipc_state = get_ipc_capability_state() if runtime_filter_enabled else None
        except Exception:
            ipc_state = None
        lines = [
            f"# Tools in `{category}`",
            str(info["description"]),
            f"Active operating mode: `{active_mode.value}`",
            "",
        ]
        maturity_filter = maturity.strip().casefold()
        for tool_name in tools:
            if maturity_filter:
                from ..capabilities import get as get_capability

                capability = get_capability(tool_name)
                if capability is None or capability.maturity.value != maturity_filter:
                    continue
            mode_note = _mode_availability_note(tool_name)
            runtime_note = "" if mode_note else _runtime_availability_note(tool_name, ipc_state)
            lines.append(f"- `{_display_tool_name(tool_name)}`{mode_note}{runtime_note}")
        if len(lines) == 4:
            lines.append(f"No tools matched maturity='{maturity}'.")
        return "\n".join(lines)

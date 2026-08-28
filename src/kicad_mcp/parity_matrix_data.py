"""Embedded capability-parity matrix. GENERATED — do not edit by hand.

Synchronized from docs/compatibility/capability-parity-matrix.yaml by
scripts/build_parity_matrix.py. Regenerate with:
    uv run python scripts/build_parity_matrix.py
"""

from __future__ import annotations

import json
from typing import Any

_RAW = r"""
{
  "schemaVersion": 1,
  "updated": "2026-08-28",
  "kicad_baseline": "10.0.x",
  "status_vocabulary": {
    "covered": "A registered MCP tool fully drives this capability.",
    "partial": "Some MCP support exists but with a tracked limitation (heuristic estimate, optional/auth-gated dependency, hidden/orphaned tool, or a manual KiCad step).",
    "gap": "KiCad exposes this programmatically (cli/ipc/file) but no MCP tool drives it yet.",
    "gui-only-no-api": "KiCad only offers this interactively; no cli/ipc/file path exists. Excluded from the coverage denominator (a KiCad API limit, not ours)."
  },
  "channel_vocabulary": {
    "file": "Direct .kicad_sch / .kicad_pcb / .kicad_pro S-expression or JSON manipulation.",
    "cli": "Driven through the kicad-cli subprocess.",
    "ipc": "Driven through the KiCad IPC / kipy API against a running KiCad.",
    "gui-only": "Only reachable through interactive KiCad UI; no headless surface."
  },
  "domains": {
    "schematic_edit": {
      "description": "Symbol/wire/label/bus/hierarchy/power/no-connect/annotate/ERC editing of .kicad_sch.",
      "capabilities": [
        {
          "capability": "Place a library symbol at an absolute coordinate",
          "kicad_channel": "file",
          "mcp_tool": "sch_add_symbol",
          "status": "covered",
          "kicad_version_introduced": "10.0.x",
          "notes": "sch_add_component covers the by-library convenience path."
        },
        {
          "capability": "Move a placed symbol",
          "kicad_channel": "file",
          "mcp_tool": "sch_move_symbol",
          "status": "covered",
          "kicad_version_introduced": "10.0.x",
          "notes": ""
        },
        {
          "capability": "Delete a placed symbol and attached wires",
          "kicad_channel": "file",
          "mcp_tool": "sch_delete_symbol",
          "status": "covered",
          "kicad_version_introduced": "10.0.x",
          "notes": ""
        },
        {
          "capability": "Add a wire between points / between pins",
          "kicad_channel": "file",
          "mcp_tool": "sch_route_wire_between_pins",
          "status": "covered",
          "kicad_version_introduced": "10.0.x",
          "notes": "sch_add_wire for raw segments; sch_add_missing_junctions repairs T-junctions."
        },
        {
          "capability": "Add local / global / hierarchical labels",
          "kicad_channel": "file",
          "mcp_tool": "sch_add_label",
          "status": "covered",
          "kicad_version_introduced": "10.0.x",
          "notes": "sch_add_global_label, sch_add_hierarchical_label, sch_move_label, sch_delete_label, sch_modify_label (justify)."
        },
        {
          "capability": "Add a bus and bus-wire entries",
          "kicad_channel": "file",
          "mcp_tool": "sch_add_bus",
          "status": "covered",
          "kicad_version_introduced": "10.0.x",
          "notes": "sch_add_bus_wire_entry for member entries."
        },
        {
          "capability": "Add a power symbol / power flag",
          "kicad_channel": "file",
          "mcp_tool": "sch_add_power_symbol",
          "status": "covered",
          "kicad_version_introduced": "10.0.x",
          "notes": "sch_check_power_flags audits coverage."
        },
        {
          "capability": "Add no-connect markers",
          "kicad_channel": "file",
          "mcp_tool": "sch_add_no_connect",
          "status": "covered",
          "kicad_version_introduced": "10.0.x",
          "notes": ""
        },
        {
          "capability": "Create and wire hierarchical sheets",
          "kicad_channel": "file",
          "mcp_tool": "sch_create_sheet",
          "status": "covered",
          "kicad_version_introduced": "10.0.x",
          "notes": "sch_list_sheets / sch_get_sheet_info for inspection."
        },
        {
          "capability": "Annotate references",
          "kicad_channel": "file",
          "mcp_tool": "sch_annotate",
          "status": "covered",
          "kicad_version_introduced": "10.0.x",
          "notes": ""
        },
        {
          "capability": "Run ERC and inspect violations",
          "kicad_channel": "cli",
          "mcp_tool": "run_erc",
          "status": "covered",
          "kicad_version_introduced": "10.0.x",
          "notes": "erc_set_rule_severity / erc_list_rules tune severities."
        },
        {
          "capability": "Modify a symbol property by reference",
          "kicad_channel": "ipc",
          "mcp_tool": "sch_modify_property",
          "status": "partial",
          "kicad_version_introduced": "10.0.x",
          "notes": "Round-trip-safe edit primitive (utils/schematic_roundtrip) with a corruption guard exists (P2-T1); testing showed kicad-sch-api 0.5.x drops global_label on save, so writes refuse+restore rather than silently corrupt (K5). Migrating each regex write path through the guarded primitive is incremental."
        },
        {
          "capability": "Swap pins / gates",
          "kicad_channel": "file",
          "mcp_tool": "sch_swap_pins",
          "status": "partial",
          "kicad_version_introduced": "10.0.x",
          "notes": "Experimental; sch_swap_gates is also experimental and profile-gated."
        },
        {
          "capability": "Interactive symbol graphic drawing in the editor",
          "kicad_channel": "gui-only",
          "mcp_tool": null,
          "status": "gui-only-no-api",
          "kicad_version_introduced": "10.0.x",
          "notes": "Custom symbol bodies are created via lib_create_custom_symbol; freehand editor drawing is GUI-only."
        }
      ]
    },
    "pcb_edit": {
      "description": "Footprint place/move, track/via/zone/stackup/rules/groups/teardrops/fanout on .kicad_pcb.",
      "capabilities": [
        {
          "capability": "Place / move a footprint",
          "kicad_channel": "ipc",
          "mcp_tool": "pcb_place_component",
          "status": "covered",
          "kicad_version_introduced": "10.0.x",
          "notes": "pcb_move_footprint / pcb_move_component for relocation."
        },
        {
          "capability": "Add a track / route a trace",
          "kicad_channel": "ipc",
          "mcp_tool": "pcb_add_track",
          "status": "covered",
          "kicad_version_introduced": "10.0.x",
          "notes": "pcb_route_trace, pcb_add_tracks_bulk for batches."
        },
        {
          "capability": "Add through / blind / micro vias",
          "kicad_channel": "ipc",
          "mcp_tool": "pcb_add_via",
          "status": "covered",
          "kicad_version_introduced": "10.0.x",
          "notes": "pcb_add_blind_via, pcb_add_microvia."
        },
        {
          "capability": "Add and refill copper zones",
          "kicad_channel": "ipc",
          "mcp_tool": "pcb_add_copper_zone",
          "status": "covered",
          "kicad_version_introduced": "10.0.x",
          "notes": "pcb_add_zone, pcb_refill_zones."
        },
        {
          "capability": "Read / set the layer stackup",
          "kicad_channel": "file",
          "mcp_tool": "pcb_set_stackup",
          "status": "covered",
          "kicad_version_introduced": "10.0.x",
          "notes": "pcb_get_stackup for inspection."
        },
        {
          "capability": "Read / set design rules",
          "kicad_channel": "file",
          "mcp_tool": "pcb_set_design_rules",
          "status": "covered",
          "kicad_version_introduced": "10.0.x",
          "notes": "pcb_get_design_rules; drc_rule_create/delete/enable for custom rules."
        },
        {
          "capability": "Assign net classes",
          "kicad_channel": "file",
          "mcp_tool": "pcb_set_net_class",
          "status": "covered",
          "kicad_version_introduced": "10.0.x",
          "notes": "route_set_net_class_rules for routing constraints."
        },
        {
          "capability": "Add teardrops",
          "kicad_channel": "ipc",
          "mcp_tool": "pcb_add_teardrops",
          "status": "covered",
          "kicad_version_introduced": "10.0.x",
          "notes": ""
        },
        {
          "capability": "BGA / fine-pitch fanout",
          "kicad_channel": "ipc",
          "mcp_tool": "pcb_bga_fanout",
          "status": "covered",
          "kicad_version_introduced": "10.0.x",
          "notes": ""
        },
        {
          "capability": "Set the board outline",
          "kicad_channel": "ipc",
          "mcp_tool": "pcb_set_board_outline",
          "status": "covered",
          "kicad_version_introduced": "10.0.x",
          "notes": ""
        },
        {
          "capability": "Auto-place footprints from schematic",
          "kicad_channel": "ipc",
          "mcp_tool": "pcb_auto_place_by_schematic",
          "status": "partial",
          "kicad_version_introduced": "10.0.x",
          "notes": "Force-directed placement now stops by deterministic convergence (K7); placement scoring now includes return-path constraints (high-speed interface grouping via InterfaceSpec), mechanical mount-hole clearance, connector edge-placement specs, and before/after score evidence; explainable per-category FAIL/WARN output is emitted after each auto-placement run. Current-path (multi-sink power delivery) and board-level high-speed routing constraints remain P4-T2 partial."
        },
        {
          "capability": "Run DRC and inspect violations",
          "kicad_channel": "cli",
          "mcp_tool": "run_drc",
          "status": "covered",
          "kicad_version_introduced": "10.0.x",
          "notes": "drc_add_exclusion / drc_validate_exclusions manage waivers."
        },
        {
          "capability": "Manage design blocks / reusable groups",
          "kicad_channel": "file",
          "mcp_tool": "pcb_block_create_from_selection",
          "status": "covered",
          "kicad_version_introduced": "10.0.x",
          "notes": "pcb_block_list, pcb_block_place."
        },
        {
          "capability": "Read / set board groups",
          "kicad_channel": "ipc",
          "mcp_tool": "pcb_get_groups",
          "status": "covered",
          "kicad_version_introduced": "10.0.x",
          "notes": "pcb_get_groups for inspection; pcb_group_by_function and pcb_block_* for grouping."
        },
        {
          "capability": "Read / set drawing origin",
          "kicad_channel": "ipc",
          "mcp_tool": "pcb_set_origin",
          "status": "covered",
          "kicad_version_introduced": "10.0.x",
          "notes": "pcb_get_origin / pcb_set_origin."
        },
        {
          "capability": "Begin / push / revert an IPC commit transaction",
          "kicad_channel": "ipc",
          "mcp_tool": "pcb_push_commit",
          "status": "covered",
          "kicad_version_introduced": "10.0.x",
          "notes": "pcb_begin_commit / pcb_push_commit / pcb_drop_commit / pcb_revert expose the native KiCad commit lifecycle. Transaction participation is limited to reviewed verified mutations; unsupported writes fail before side effects while a native-live session is active."
        },
        {
          "capability": "Report verified native-live transaction and recovery state",
          "kicad_channel": "ipc",
          "mcp_tool": "pcb_get_live_edit_state",
          "status": "covered",
          "kicad_version_introduced": "10.0.x",
          "notes": "Path-free state reports board fingerprint, verified/ambiguous mutation counts, recovery requirement, and terminal outcome without representing file-backed or schematic writes as native-live IPC."
        },
        {
          "capability": "Interactive push-and-shove routing",
          "kicad_channel": "gui-only",
          "mcp_tool": null,
          "status": "gui-only-no-api",
          "kicad_version_introduced": "10.0.x",
          "notes": "KiCad's interactive router (push/shove, walkaround) has no IPC/CLI surface."
        }
      ]
    },
    "routing": {
      "description": "Autoroute, length/skew tuning, diff-pair, and interactive routing.",
      "capabilities": [
        {
          "capability": "Route a single track / pad-to-pad",
          "kicad_channel": "ipc",
          "mcp_tool": "route_single_track",
          "status": "covered",
          "kicad_version_introduced": "10.0.x",
          "notes": "route_from_pad_to_pad."
        },
        {
          "capability": "Route a differential pair",
          "kicad_channel": "ipc",
          "mcp_tool": "route_differential_pair",
          "status": "covered",
          "kicad_version_introduced": "10.0.x",
          "notes": ""
        },
        {
          "capability": "Tune track / diff-pair length",
          "kicad_channel": "file",
          "mcp_tool": "route_tune_length",
          "status": "covered",
          "kicad_version_introduced": "10.0.x",
          "notes": "tune_diff_pair_length, route_tune_time_domain, tuning-profile tools."
        },
        {
          "capability": "Full autoroute (FreeRouting orchestration)",
          "kicad_channel": "cli",
          "mcp_tool": "route_autoroute_freerouting",
          "status": "partial",
          "kicad_version_introduced": "10.0.x",
          "notes": "Routes headlessly (Docker/JAR); the routed SES is now applied headlessly by route_apply_ses (utils/router_core writes segments/vias into the .kicad_pcb), closing the former GUI step (P4-T1). Status stays partial: FreeRouting's own determinism is bounded and the SES coordinate transform assumes KiCad's standard Specctra export convention (verified end-to-end only in the KiCad CI job)."
        },
        {
          "capability": "Export Specctra DSN / import routed SES",
          "kicad_channel": "cli",
          "mcp_tool": "route_export_dsn",
          "status": "partial",
          "kicad_version_introduced": "10.0.x",
          "notes": "route_export_dsn attempts headless kicad-cli specctra export, else a clear human-gated manual step; the routed SES is applied fully headlessly by route_apply_ses (deterministic, idempotent, round-trip-safe via utils/router_core, P4-T1) -- no GUI import. Export side stays partial when kicad-cli lacks headless specctra export."
        },
        {
          "capability": "Set per-net-class routing rules",
          "kicad_channel": "file",
          "mcp_tool": "route_set_net_class_rules",
          "status": "covered",
          "kicad_version_introduced": "10.0.x",
          "notes": ""
        },
        {
          "capability": "Interactive length tuning / meander drawing",
          "kicad_channel": "gui-only",
          "mcp_tool": null,
          "status": "gui-only-no-api",
          "kicad_version_introduced": "10.0.x",
          "notes": "Interactive trace tuning UX is GUI-only; programmatic tuning is modeled by route_tune_length."
        }
      ]
    },
    "library": {
      "description": "Symbol/footprint/3D generation + assignment + part sourcing.",
      "capabilities": [
        {
          "capability": "Search symbols / footprints",
          "kicad_channel": "file",
          "mcp_tool": "lib_search_symbols",
          "status": "covered",
          "kicad_version_introduced": "10.0.x",
          "notes": "lib_search_footprints, lib_list_libraries, lib_rebuild_index."
        },
        {
          "capability": "Assign a footprint to a symbol",
          "kicad_channel": "file",
          "mcp_tool": "lib_assign_footprint",
          "status": "covered",
          "kicad_version_introduced": "10.0.x",
          "notes": ""
        },
        {
          "capability": "Create a custom symbol",
          "kicad_channel": "file",
          "mcp_tool": "lib_create_custom_symbol",
          "status": "covered",
          "kicad_version_introduced": "10.0.x",
          "notes": "lib_generate_symbol_from_pintable for pin-table-driven generation."
        },
        {
          "capability": "Generate an IPC-7351 footprint",
          "kicad_channel": "file",
          "mcp_tool": "lib_generate_footprint_ipc7351",
          "status": "partial",
          "kicad_version_introduced": "10.0.x",
          "notes": "Footprint family coverage now includes chip passives, SOT-23/SOT-223/SOT-89, SOT-363/SOT-26, SC-70/SOT-323, SOD-123/SOD-323, DO-214 (SMA/SMB/SMC), DPAK/TO-252, D2PAK/TO-263, SOIC/SOP/SSOP/TSSOP, QFP, QFN/DFN, BGA, and PinHeader; datasheet/3D model consistency remains partial."
        },
        {
          "capability": "Assign / manage 3D models",
          "kicad_channel": "file",
          "mcp_tool": "lib_set_3d_model_path",
          "status": "covered",
          "kicad_version_introduced": "10.0.x",
          "notes": "lib_bulk_assign_3d_models, lib_search_3d_models, lib_remove_3d_model."
        },
        {
          "capability": "Source live component data (price/stock/lifecycle)",
          "kicad_channel": "file",
          "mcp_tool": "lib_search_components",
          "status": "partial",
          "kicad_version_introduced": "10.0.x",
          "notes": "Live JLCPCB, Nexar, DigiKey, and Mouser sourcing clients are implemented; lib_check_sourcing_policy emits structured stock, price, lifecycle, RoHS, and AVL policy verdicts. Remaining P4-T3 work is datasheet-grounded footprint/3D hard gates and provider manufacturer metadata normalization."
        },
        {
          "capability": "Recommend / bind a part to a symbol",
          "kicad_channel": "file",
          "mcp_tool": "lib_recommend_part",
          "status": "partial",
          "kicad_version_introduced": "10.0.x",
          "notes": "lib_bind_part_to_symbol; depends on the same sourcing backends as above."
        }
      ]
    },
    "analysis": {
      "description": "SI / PI / EMC / thermal / DFM / SPICE analysis.",
      "capabilities": [
        {
          "capability": "Single-ended / differential trace impedance",
          "kicad_channel": "file",
          "mcp_tool": "si_calculate_trace_impedance",
          "status": "partial",
          "kicad_version_introduced": "10.0.x",
          "notes": "First-order closed-form (IPC-2141/Wheeler) estimate ~5-10% (work order K4); field-solver accuracy is Phase 3 (P3-T1)."
        },
        {
          "capability": "Differential-pair skew gate",
          "kicad_channel": "file",
          "mcp_tool": "si_check_differential_pair_skew",
          "status": "partial",
          "kicad_version_introduced": "10.0.x",
          "notes": "Real PASS/WARN/FAIL verdict with intent-derived skew budget (P1-T3); localized intra-pair phase-skew / mode-conversion is Phase 3 (P3-T3)."
        },
        {
          "capability": "Length-matching validation",
          "kicad_channel": "file",
          "mcp_tool": "si_validate_length_matching",
          "status": "partial",
          "kicad_version_introduced": "10.0.x",
          "notes": "Three-level PASS/WARN/FAIL verdict against a tolerance budget (P1-T3); track-length based heuristic."
        },
        {
          "capability": "Synthesize a stackup for target interfaces",
          "kicad_channel": "file",
          "mcp_tool": "si_synthesize_stackup_for_interfaces",
          "status": "covered",
          "kicad_version_introduced": "10.0.x",
          "notes": "si_generate_stackup, si_bind_interfaces_to_net_classes, si_list_dielectric_materials."
        },
        {
          "capability": "High-speed channel insertion-loss / eye analysis",
          "kicad_channel": "file",
          "mcp_tool": "si_analyze_high_speed_channel",
          "status": "partial",
          "kicad_version_introduced": "10.0.x",
          "notes": "Closed-form lossy-line insertion loss (conductor skin-effect + dielectric loss) with a loss-limited eye and PASS/WARN/FAIL verdict; when an ngspice CLI is present the insertion loss is measured from an RLGC-ladder AC sweep (utils/channel + solver seam). Full S-parameter / IBIS-AMI channel simulation remains a future upgrade."
        },
        {
          "capability": "DC IR-drop / voltage-drop analysis",
          "kicad_channel": "file",
          "mcp_tool": "pdn_calculate_voltage_drop",
          "status": "partial",
          "kicad_version_introduced": "10.0.x",
          "notes": "pdn_calculate_voltage_drop is a first-order single-trace lumped estimate, now with an IPC-2221 current-density fusing / temperature-rise PASS/WARN/FAIL verdict; check_power_integrity runs a genuine distributed multi-load resistive PDN mesh (DC drop + frequency-domain Z(f)), labeled solver-grade via the seam (utils/solver_seams.pdn_mesh_method). Remaining P3-T2 upgrade: a 2-D copper-plane field solve."
        },
        {
          "capability": "Decoupling recommendation / power-plane generation",
          "kicad_channel": "file",
          "mcp_tool": "pdn_recommend_decoupling_caps",
          "status": "partial",
          "kicad_version_introduced": "10.0.x",
          "notes": "pdn_generate_power_plane covered; frequency-domain PDN target-Z checking now delivered via check_power_integrity (pdn_mesh Z(f) vs target_impedance_ohm with violations); a full plane-capacitance field model remains a future upgrade."
        },
        {
          "capability": "Thermal via / copper-pour sizing",
          "kicad_channel": "file",
          "mcp_tool": "thermal_calculate_via_count",
          "status": "partial",
          "kicad_version_introduced": "10.0.x",
          "notes": "thermal_check_copper_pour; first-order theta_JA / via-count rule of thumb labeled honestly via the solver seam (utils/solver_seams.thermal_method); for distributed spreading use thermal_simulate_plane_spreading."
        },
        {
          "capability": "Copper-plane thermal spreading (2-D FD solve)",
          "kicad_channel": "file",
          "mcp_tool": "thermal_simulate_plane_spreading",
          "status": "partial",
          "kicad_version_introduced": "10.0.x",
          "notes": "Genuine 2-D finite-difference steady-state heat-spreading solve over the copper plane (utils/thermal_solver + solver_seams.thermal_fd_method) with peak/average temperature rise and a PASS/WARN/FAIL verdict; not a 3-D FEA with airflow / board-stack conduction (full FEA remains a future upgrade)."
        },
        {
          "capability": "EMC layout compliance checks",
          "kicad_channel": "file",
          "mcp_tool": "emc_run_full_compliance",
          "status": "partial",
          "kicad_version_introduced": "10.0.x",
          "notes": "Presence/heuristic checks with fixed Er (work order K2/K10); EM-result-based, standard-named, fail-capable checks are Phase 3 (P3-T5)."
        },
        {
          "capability": "DFM manufacturer checks and cost",
          "kicad_channel": "file",
          "mcp_tool": "dfm_run_manufacturer_check",
          "status": "covered",
          "kicad_version_introduced": "10.0.x",
          "notes": "dfm_load_manufacturer_profile, dfm_calculate_manufacturing_cost."
        },
        {
          "capability": "SPICE simulation (op / AC / transient / DC sweep)",
          "kicad_channel": "cli",
          "mcp_tool": "sim_run_transient",
          "status": "covered",
          "kicad_version_introduced": "10.0.x",
          "notes": "ngspice engine; sim_run_operating_point/ac_analysis/dc_sweep, sim_check_stability."
        },
        {
          "capability": "2D/3D field / EM solver for impedance & coupling",
          "kicad_channel": "file",
          "mcp_tool": "si_get_solver_capabilities",
          "status": "partial",
          "kicad_version_introduced": "10.0.x",
          "notes": "si_get_solver_capabilities exposes the configured solver seams and explicit solver-unavailable policy. No full field/EM backend is integrated yet; closed-form results remain critic-only and blocked for release signoff unless a solver-grade backend is configured."
        }
      ]
    },
    "export": {
      "description": "Gerber/drill/BOM/POS/STEP/ODB/IPC2581/SVG/PDF/3D manufacturing outputs.",
      "capabilities": [
        {
          "capability": "Gerber export",
          "kicad_channel": "cli",
          "mcp_tool": "export_gerber",
          "status": "covered",
          "kicad_version_introduced": "10.0.x",
          "notes": ""
        },
        {
          "capability": "Drill export",
          "kicad_channel": "cli",
          "mcp_tool": "export_drill",
          "status": "covered",
          "kicad_version_introduced": "10.0.x",
          "notes": ""
        },
        {
          "capability": "BOM export",
          "kicad_channel": "cli",
          "mcp_tool": "export_bom",
          "status": "covered",
          "kicad_version_introduced": "10.0.x",
          "notes": "export_sch_python_bom for the Python BOM path."
        },
        {
          "capability": "Pick-and-place (POS/CPL) export",
          "kicad_channel": "cli",
          "mcp_tool": "export_pick_and_place",
          "status": "covered",
          "kicad_version_introduced": "10.0.x",
          "notes": "mfg_correct_cpl_rotations for fab rotation fixups."
        },
        {
          "capability": "STEP / 3D model export",
          "kicad_channel": "cli",
          "mcp_tool": "export_step",
          "status": "covered",
          "kicad_version_introduced": "10.0.x",
          "notes": "export_stepz, export_glb, export_vrml, export_stl, export_ply, export_brep, export_u3d."
        },
        {
          "capability": "IPC-2581 / ODB++ interchange export",
          "kicad_channel": "cli",
          "mcp_tool": "export_ipc2581",
          "status": "covered",
          "kicad_version_introduced": "10.0.x",
          "notes": "export_odb."
        },
        {
          "capability": "SVG / PDF / DXF documentation export",
          "kicad_channel": "cli",
          "mcp_tool": "export_pcb_pdf",
          "status": "covered",
          "kicad_version_introduced": "10.0.x",
          "notes": "export_sch_pdf, export_svg, export_dxf, export_sch_svg, export_sch_dxf."
        },
        {
          "capability": "Netlist export",
          "kicad_channel": "cli",
          "mcp_tool": "export_netlist",
          "status": "covered",
          "kicad_version_introduced": "10.0.x",
          "notes": "export_spice_netlist."
        },
        {
          "capability": "Release-gated manufacturing package",
          "kicad_channel": "cli",
          "mcp_tool": "export_manufacturing_package",
          "status": "covered",
          "kicad_version_introduced": "10.0.x",
          "notes": "Hard-gated on project_quality_gate PASS."
        }
      ]
    },
    "project": {
      "description": "Variants, embedded files, jobsets, VCS, and design intent.",
      "capabilities": [
        {
          "capability": "Assembly variants (create / activate / diff / export)",
          "kicad_channel": "file",
          "mcp_tool": "variant_create",
          "status": "covered",
          "kicad_version_introduced": "10.0.x",
          "notes": "variant_set_active, variant_diff_bom, variant_export_bom, variant_clone."
        },
        {
          "capability": "Embedded project files",
          "kicad_channel": "file",
          "mcp_tool": "project_embed_file",
          "status": "covered",
          "kicad_version_introduced": "10.0.x",
          "notes": "project_list_embedded_files, project_extract_embedded_file, project_remove_embedded_file."
        },
        {
          "capability": "Job sets (export automation)",
          "kicad_channel": "cli",
          "mcp_tool": "jobset_export",
          "status": "covered",
          "kicad_version_introduced": "10.0.x",
          "notes": "jobset_list_templates, jobset_run, jobset_validate."
        },
        {
          "capability": "Version-control checkpoints",
          "kicad_channel": "file",
          "mcp_tool": "vcs_commit_checkpoint",
          "status": "covered",
          "kicad_version_introduced": "10.0.x",
          "notes": "vcs_init_git, vcs_list_checkpoints, vcs_restore_checkpoint, vcs_diff_with_checkpoint, vcs_tag_release."
        },
        {
          "capability": "Capture / infer design intent and spec",
          "kicad_channel": "file",
          "mcp_tool": "project_set_design_intent",
          "status": "covered",
          "kicad_version_introduced": "10.0.x",
          "notes": "project_get_design_spec, project_infer_design_spec, project_validate_design_spec."
        }
      ]
    },
    "cosmetics": {
      "description": "Silk, board art, drawing sheet / title block, fab notes, fiducials, mounting holes.",
      "capabilities": [
        {
          "capability": "Add silkscreen / fab text",
          "kicad_channel": "ipc",
          "mcp_tool": "pcb_add_text",
          "status": "covered",
          "kicad_version_introduced": "10.0.x",
          "notes": ""
        },
        {
          "capability": "Add a barcode / data-matrix",
          "kicad_channel": "file",
          "mcp_tool": "pcb_add_barcode",
          "status": "covered",
          "kicad_version_introduced": "10.0.x",
          "notes": ""
        },
        {
          "capability": "Add fiducials",
          "kicad_channel": "ipc",
          "mcp_tool": "pcb_add_fiducial_marks",
          "status": "covered",
          "kicad_version_introduced": "10.0.x",
          "notes": ""
        },
        {
          "capability": "Add mounting holes",
          "kicad_channel": "ipc",
          "mcp_tool": "pcb_add_mounting_holes",
          "status": "covered",
          "kicad_version_introduced": "10.0.x",
          "notes": ""
        },
        {
          "capability": "Add inner-layer graphics to a footprint",
          "kicad_channel": "file",
          "mcp_tool": "add_footprint_inner_layer_graphic",
          "status": "covered",
          "kicad_version_introduced": "10.0.x",
          "notes": ""
        },
        {
          "capability": "Set drawing-sheet title-block fields",
          "kicad_channel": "ipc",
          "mcp_tool": "pcb_set_title_block_info",
          "status": "covered",
          "kicad_version_introduced": "10.0.x",
          "notes": "pcb_set_title_block_info."
        },
        {
          "capability": "Import a logo/bitmap as board art (bitmap2component)",
          "kicad_channel": "file",
          "mcp_tool": "pcb_add_bitmap_board_art",
          "status": "covered",
          "kicad_version_introduced": "10.0.x",
          "notes": "pcb_add_bitmap_board_art imports bitmap/logo pixels into deterministic filled board-art rectangles on the requested PCB graphics layer. It intentionally avoids private paths and caps generated shape count for reviewable output."
        },
        {
          "capability": "Custom drawing-sheet (.kicad_wks) template design",
          "kicad_channel": "gui-only",
          "mcp_tool": null,
          "status": "gui-only-no-api",
          "kicad_version_introduced": "10.0.x",
          "notes": "The page-layout editor is interactive; no headless drawing-sheet authoring surface."
        }
      ]
    }
  }
}
"""

CAPABILITY_PARITY_MATRIX: dict[str, Any] = json.loads(_RAW)

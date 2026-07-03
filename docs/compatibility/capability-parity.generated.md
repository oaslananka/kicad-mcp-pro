# KiCad Capability Parity (generated)

Machine-generated from `docs/compatibility/capability-parity-matrix.yaml`. Refresh with `uv run python scripts/build_parity_matrix.py`.

KiCad baseline: `10.0.x` · Updated: 2026-06-17

**Overall: 58 / 76 programmatically-reachable capabilities driven = 76.3%** (18 partial, 0 gap; 4 GUI-only with no KiCad API, excluded from the denominator).

## Coverage by domain

| Domain | Coverage | Covered | Partial | Gap | GUI-only (no API) |
|---|---:|---:|---:|---:|---:|
| `schematic_edit` | 84.6% | 11 | 2 | 0 | 1 |
| `pcb_edit` | 93.8% | 15 | 1 | 0 | 1 |
| `routing` | 66.7% | 4 | 2 | 0 | 1 |
| `library` | 57.1% | 4 | 3 | 0 | 0 |
| `analysis` | 23.1% | 3 | 10 | 0 | 0 |
| `export` | 100.0% | 9 | 0 | 0 | 0 |
| `project` | 100.0% | 5 | 0 | 0 | 0 |
| `cosmetics` | 100.0% | 7 | 0 | 0 | 1 |
| **Overall** | **76.3%** | 58 | 18 | 0 | 4 |

## Closeable surface (gap, then partial)

| Domain | Capability | Status | Channel | MCP tool | Notes |
|---|---|---|---|---|---|
| `analysis` | 2D/3D field / EM solver for impedance & coupling | `partial` | `file` | `si_get_solver_capabilities` | si_get_solver_capabilities exposes the configured solver seams and explicit solver-unavailable policy. No full field/EM backend is integrated yet; closed-form results remain critic-only and blocked for release signoff unless a solver-grade backend is configured. |
| `analysis` | Copper-plane thermal spreading (2-D FD solve) | `partial` | `file` | `thermal_simulate_plane_spreading` | Genuine 2-D finite-difference steady-state heat-spreading solve over the copper plane (utils/thermal_solver + solver_seams.thermal_fd_method) with peak/average temperature rise and a PASS/WARN/FAIL verdict; not a 3-D FEA with airflow / board-stack conduction (full FEA remains a future upgrade). |
| `analysis` | DC IR-drop / voltage-drop analysis | `partial` | `file` | `pdn_calculate_voltage_drop` | pdn_calculate_voltage_drop is a first-order single-trace lumped estimate, now with an IPC-2221 current-density fusing / temperature-rise PASS/WARN/FAIL verdict; check_power_integrity runs a genuine distributed multi-load resistive PDN mesh (DC drop + frequency-domain Z(f)), labeled solver-grade via the seam (utils/solver_seams.pdn_mesh_method). Remaining P3-T2 upgrade: a 2-D copper-plane field solve. |
| `analysis` | Decoupling recommendation / power-plane generation | `partial` | `file` | `pdn_recommend_decoupling_caps` | pdn_generate_power_plane covered; frequency-domain PDN target-Z checking now delivered via check_power_integrity (pdn_mesh Z(f) vs target_impedance_ohm with violations); a full plane-capacitance field model remains a future upgrade. |
| `analysis` | Differential-pair skew gate | `partial` | `file` | `si_check_differential_pair_skew` | Real PASS/WARN/FAIL verdict with intent-derived skew budget (P1-T3); localized intra-pair phase-skew / mode-conversion is Phase 3 (P3-T3). |
| `analysis` | EMC layout compliance checks | `partial` | `file` | `emc_run_full_compliance` | Presence/heuristic checks with fixed Er (work order K2/K10); EM-result-based, standard-named, fail-capable checks are Phase 3 (P3-T5). |
| `analysis` | High-speed channel insertion-loss / eye analysis | `partial` | `file` | `si_analyze_high_speed_channel` | Closed-form lossy-line insertion loss (conductor skin-effect + dielectric loss) with a loss-limited eye and PASS/WARN/FAIL verdict; when an ngspice CLI is present the insertion loss is measured from an RLGC-ladder AC sweep (utils/channel + solver seam). Full S-parameter / IBIS-AMI channel simulation remains a future upgrade. |
| `analysis` | Length-matching validation | `partial` | `file` | `si_validate_length_matching` | Three-level PASS/WARN/FAIL verdict against a tolerance budget (P1-T3); track-length based heuristic. |
| `analysis` | Single-ended / differential trace impedance | `partial` | `file` | `si_calculate_trace_impedance` | First-order closed-form (IPC-2141/Wheeler) estimate ~5-10% (work order K4); field-solver accuracy is Phase 3 (P3-T1). |
| `analysis` | Thermal via / copper-pour sizing | `partial` | `file` | `thermal_calculate_via_count` | thermal_check_copper_pour; first-order theta_JA / via-count rule of thumb labeled honestly via the solver seam (utils/solver_seams.thermal_method); for distributed spreading use thermal_simulate_plane_spreading. |
| `library` | Generate an IPC-7351 footprint | `partial` | `file` | `lib_generate_footprint_ipc7351` | Footprint family coverage is limited (work order K10: SOT-23 implemented, SOT-223/SOT-89 not yet); datasheet/IPC validation hard-gate is Phase 4 (P4-T3). |
| `library` | Recommend / bind a part to a symbol | `partial` | `file` | `lib_recommend_part` | lib_bind_part_to_symbol; depends on the same sourcing backends as above. |
| `library` | Source live component data (price/stock/lifecycle) | `partial` | `file` | `lib_search_components` | Live JLCPCB, Nexar, DigiKey, and Mouser sourcing clients are implemented; Nexar/DigiKey/Mouser are opt-in and auth-gated. Remaining P4-T3 work is full AVL/lifecycle policy enforcement and datasheet-grounded footprint/3D hard gates. |
| `pcb_edit` | Auto-place footprints from schematic | `partial` | `ipc` | `pcb_auto_place_by_schematic` | Force-directed placement now stops by deterministic convergence and disables the wall-clock safety valve by default (K7); remaining P4-T2 work is deeper electrical/thermal/return-path scoring beyond net-weighted placement. |
| `routing` | Export Specctra DSN / import routed SES | `partial` | `cli` | `route_export_dsn` | route_export_dsn attempts headless kicad-cli specctra export, else a clear human-gated manual step; the routed SES is applied fully headlessly by route_apply_ses (deterministic, idempotent, round-trip-safe via utils/router_core, P4-T1) -- no GUI import. Export side stays partial when kicad-cli lacks headless specctra export. |
| `routing` | Full autoroute (FreeRouting orchestration) | `partial` | `cli` | `route_autoroute_freerouting` | Routes headlessly (Docker/JAR); the routed SES is now applied headlessly by route_apply_ses (utils/router_core writes segments/vias into the .kicad_pcb), closing the former GUI step (P4-T1). Status stays partial: FreeRouting's own determinism is bounded and the SES coordinate transform assumes KiCad's standard Specctra export convention (verified end-to-end only in the KiCad CI job). |
| `schematic_edit` | Modify a symbol property by reference | `partial` | `ipc` | `sch_modify_property` | Round-trip-safe edit primitive (utils/schematic_roundtrip) with a corruption guard exists (P2-T1); testing showed kicad-sch-api 0.5.x drops global_label on save, so writes refuse+restore rather than silently corrupt (K5). Migrating each regex write path through the guarded primitive is incremental. |
| `schematic_edit` | Swap pins / gates | `partial` | `file` | `sch_swap_pins` | Experimental; sch_swap_gates is also experimental and profile-gated. |

## Full matrix

### `schematic_edit`

Symbol/wire/label/bus/hierarchy/power/no-connect/annotate/ERC editing of .kicad_sch.

| Capability | Channel | MCP tool | Status | KiCad | Notes |
|---|---|---|---|---|---|
| Place a library symbol at an absolute coordinate | `file` | `sch_add_symbol` | `covered` | 10.0.x | sch_add_component covers the by-library convenience path. |
| Move a placed symbol | `file` | `sch_move_symbol` | `covered` | 10.0.x |  |
| Delete a placed symbol and attached wires | `file` | `sch_delete_symbol` | `covered` | 10.0.x |  |
| Add a wire between points / between pins | `file` | `sch_route_wire_between_pins` | `covered` | 10.0.x | sch_add_wire for raw segments; sch_add_missing_junctions repairs T-junctions. |
| Add local / global / hierarchical labels | `file` | `sch_add_label` | `covered` | 10.0.x | sch_add_global_label, sch_add_hierarchical_label, sch_move_label, sch_delete_label. |
| Add a bus and bus-wire entries | `file` | `sch_add_bus` | `covered` | 10.0.x | sch_add_bus_wire_entry for member entries. |
| Add a power symbol / power flag | `file` | `sch_add_power_symbol` | `covered` | 10.0.x | sch_check_power_flags audits coverage. |
| Add no-connect markers | `file` | `sch_add_no_connect` | `covered` | 10.0.x |  |
| Create and wire hierarchical sheets | `file` | `sch_create_sheet` | `covered` | 10.0.x | sch_list_sheets / sch_get_sheet_info for inspection. |
| Annotate references | `file` | `sch_annotate` | `covered` | 10.0.x |  |
| Run ERC and inspect violations | `cli` | `run_erc` | `covered` | 10.0.x | erc_set_rule_severity / erc_list_rules tune severities. |
| Modify a symbol property by reference | `ipc` | `sch_modify_property` | `partial` | 10.0.x | Round-trip-safe edit primitive (utils/schematic_roundtrip) with a corruption guard exists (P2-T1); testing showed kicad-sch-api 0.5.x drops global_label on save, so writes refuse+restore rather than silently corrupt (K5). Migrating each regex write path through the guarded primitive is incremental. |
| Swap pins / gates | `file` | `sch_swap_pins` | `partial` | 10.0.x | Experimental; sch_swap_gates is also experimental and profile-gated. |
| Interactive symbol graphic drawing in the editor | `gui-only` | — | `gui-only-no-api` | 10.0.x | Custom symbol bodies are created via lib_create_custom_symbol; freehand editor drawing is GUI-only. |

### `pcb_edit`

Footprint place/move, track/via/zone/stackup/rules/groups/teardrops/fanout on .kicad_pcb.

| Capability | Channel | MCP tool | Status | KiCad | Notes |
|---|---|---|---|---|---|
| Place / move a footprint | `ipc` | `pcb_place_component` | `covered` | 10.0.x | pcb_move_footprint / pcb_move_component for relocation. |
| Add a track / route a trace | `ipc` | `pcb_add_track` | `covered` | 10.0.x | pcb_route_trace, pcb_add_tracks_bulk for batches. |
| Add through / blind / micro vias | `ipc` | `pcb_add_via` | `covered` | 10.0.x | pcb_add_blind_via, pcb_add_microvia. |
| Add and refill copper zones | `ipc` | `pcb_add_copper_zone` | `covered` | 10.0.x | pcb_add_zone, pcb_refill_zones. |
| Read / set the layer stackup | `file` | `pcb_set_stackup` | `covered` | 10.0.x | pcb_get_stackup for inspection. |
| Read / set design rules | `file` | `pcb_set_design_rules` | `covered` | 10.0.x | pcb_get_design_rules; drc_rule_create/delete/enable for custom rules. |
| Assign net classes | `file` | `pcb_set_net_class` | `covered` | 10.0.x | route_set_net_class_rules for routing constraints. |
| Add teardrops | `ipc` | `pcb_add_teardrops` | `covered` | 10.0.x |  |
| BGA / fine-pitch fanout | `ipc` | `pcb_bga_fanout` | `covered` | 10.0.x |  |
| Set the board outline | `ipc` | `pcb_set_board_outline` | `covered` | 10.0.x |  |
| Auto-place footprints from schematic | `ipc` | `pcb_auto_place_by_schematic` | `partial` | 10.0.x | Force-directed placement now stops by deterministic convergence and disables the wall-clock safety valve by default (K7); remaining P4-T2 work is deeper electrical/thermal/return-path scoring beyond net-weighted placement. |
| Run DRC and inspect violations | `cli` | `run_drc` | `covered` | 10.0.x | drc_add_exclusion / drc_validate_exclusions manage waivers. |
| Manage design blocks / reusable groups | `file` | `pcb_block_create_from_selection` | `covered` | 10.0.x | pcb_block_list, pcb_block_place. |
| Read / set board groups | `ipc` | `pcb_get_groups` | `covered` | 10.0.x | pcb_get_groups for inspection; pcb_group_by_function and pcb_block_* for grouping. |
| Read / set drawing origin | `ipc` | `pcb_set_origin` | `covered` | 10.0.x | pcb_get_origin / pcb_set_origin. |
| Begin / push / revert an IPC commit transaction | `ipc` | `pcb_push_commit` | `covered` | 10.0.x | pcb_begin_commit / push_commit / drop_commit / revert. |
| Interactive push-and-shove routing | `gui-only` | — | `gui-only-no-api` | 10.0.x | KiCad's interactive router (push/shove, walkaround) has no IPC/CLI surface. |

### `routing`

Autoroute, length/skew tuning, diff-pair, and interactive routing.

| Capability | Channel | MCP tool | Status | KiCad | Notes |
|---|---|---|---|---|---|
| Route a single track / pad-to-pad | `ipc` | `route_single_track` | `covered` | 10.0.x | route_from_pad_to_pad. |
| Route a differential pair | `ipc` | `route_differential_pair` | `covered` | 10.0.x |  |
| Tune track / diff-pair length | `file` | `route_tune_length` | `covered` | 10.0.x | tune_diff_pair_length, route_tune_time_domain, tuning-profile tools. |
| Full autoroute (FreeRouting orchestration) | `cli` | `route_autoroute_freerouting` | `partial` | 10.0.x | Routes headlessly (Docker/JAR); the routed SES is now applied headlessly by route_apply_ses (utils/router_core writes segments/vias into the .kicad_pcb), closing the former GUI step (P4-T1). Status stays partial: FreeRouting's own determinism is bounded and the SES coordinate transform assumes KiCad's standard Specctra export convention (verified end-to-end only in the KiCad CI job). |
| Export Specctra DSN / import routed SES | `cli` | `route_export_dsn` | `partial` | 10.0.x | route_export_dsn attempts headless kicad-cli specctra export, else a clear human-gated manual step; the routed SES is applied fully headlessly by route_apply_ses (deterministic, idempotent, round-trip-safe via utils/router_core, P4-T1) -- no GUI import. Export side stays partial when kicad-cli lacks headless specctra export. |
| Set per-net-class routing rules | `file` | `route_set_net_class_rules` | `covered` | 10.0.x |  |
| Interactive length tuning / meander drawing | `gui-only` | — | `gui-only-no-api` | 10.0.x | Interactive trace tuning UX is GUI-only; programmatic tuning is modeled by route_tune_length. |

### `library`

Symbol/footprint/3D generation + assignment + part sourcing.

| Capability | Channel | MCP tool | Status | KiCad | Notes |
|---|---|---|---|---|---|
| Search symbols / footprints | `file` | `lib_search_symbols` | `covered` | 10.0.x | lib_search_footprints, lib_list_libraries, lib_rebuild_index. |
| Assign a footprint to a symbol | `file` | `lib_assign_footprint` | `covered` | 10.0.x |  |
| Create a custom symbol | `file` | `lib_create_custom_symbol` | `covered` | 10.0.x | lib_generate_symbol_from_pintable for pin-table-driven generation. |
| Generate an IPC-7351 footprint | `file` | `lib_generate_footprint_ipc7351` | `partial` | 10.0.x | Footprint family coverage is limited (work order K10: SOT-23 implemented, SOT-223/SOT-89 not yet); datasheet/IPC validation hard-gate is Phase 4 (P4-T3). |
| Assign / manage 3D models | `file` | `lib_set_3d_model_path` | `covered` | 10.0.x | lib_bulk_assign_3d_models, lib_search_3d_models, lib_remove_3d_model. |
| Source live component data (price/stock/lifecycle) | `file` | `lib_search_components` | `partial` | 10.0.x | Live JLCPCB, Nexar, DigiKey, and Mouser sourcing clients are implemented; Nexar/DigiKey/Mouser are opt-in and auth-gated. Remaining P4-T3 work is full AVL/lifecycle policy enforcement and datasheet-grounded footprint/3D hard gates. |
| Recommend / bind a part to a symbol | `file` | `lib_recommend_part` | `partial` | 10.0.x | lib_bind_part_to_symbol; depends on the same sourcing backends as above. |

### `analysis`

SI / PI / EMC / thermal / DFM / SPICE analysis.

| Capability | Channel | MCP tool | Status | KiCad | Notes |
|---|---|---|---|---|---|
| Single-ended / differential trace impedance | `file` | `si_calculate_trace_impedance` | `partial` | 10.0.x | First-order closed-form (IPC-2141/Wheeler) estimate ~5-10% (work order K4); field-solver accuracy is Phase 3 (P3-T1). |
| Differential-pair skew gate | `file` | `si_check_differential_pair_skew` | `partial` | 10.0.x | Real PASS/WARN/FAIL verdict with intent-derived skew budget (P1-T3); localized intra-pair phase-skew / mode-conversion is Phase 3 (P3-T3). |
| Length-matching validation | `file` | `si_validate_length_matching` | `partial` | 10.0.x | Three-level PASS/WARN/FAIL verdict against a tolerance budget (P1-T3); track-length based heuristic. |
| Synthesize a stackup for target interfaces | `file` | `si_synthesize_stackup_for_interfaces` | `covered` | 10.0.x | si_generate_stackup, si_bind_interfaces_to_net_classes, si_list_dielectric_materials. |
| High-speed channel insertion-loss / eye analysis | `file` | `si_analyze_high_speed_channel` | `partial` | 10.0.x | Closed-form lossy-line insertion loss (conductor skin-effect + dielectric loss) with a loss-limited eye and PASS/WARN/FAIL verdict; when an ngspice CLI is present the insertion loss is measured from an RLGC-ladder AC sweep (utils/channel + solver seam). Full S-parameter / IBIS-AMI channel simulation remains a future upgrade. |
| DC IR-drop / voltage-drop analysis | `file` | `pdn_calculate_voltage_drop` | `partial` | 10.0.x | pdn_calculate_voltage_drop is a first-order single-trace lumped estimate, now with an IPC-2221 current-density fusing / temperature-rise PASS/WARN/FAIL verdict; check_power_integrity runs a genuine distributed multi-load resistive PDN mesh (DC drop + frequency-domain Z(f)), labeled solver-grade via the seam (utils/solver_seams.pdn_mesh_method). Remaining P3-T2 upgrade: a 2-D copper-plane field solve. |
| Decoupling recommendation / power-plane generation | `file` | `pdn_recommend_decoupling_caps` | `partial` | 10.0.x | pdn_generate_power_plane covered; frequency-domain PDN target-Z checking now delivered via check_power_integrity (pdn_mesh Z(f) vs target_impedance_ohm with violations); a full plane-capacitance field model remains a future upgrade. |
| Thermal via / copper-pour sizing | `file` | `thermal_calculate_via_count` | `partial` | 10.0.x | thermal_check_copper_pour; first-order theta_JA / via-count rule of thumb labeled honestly via the solver seam (utils/solver_seams.thermal_method); for distributed spreading use thermal_simulate_plane_spreading. |
| Copper-plane thermal spreading (2-D FD solve) | `file` | `thermal_simulate_plane_spreading` | `partial` | 10.0.x | Genuine 2-D finite-difference steady-state heat-spreading solve over the copper plane (utils/thermal_solver + solver_seams.thermal_fd_method) with peak/average temperature rise and a PASS/WARN/FAIL verdict; not a 3-D FEA with airflow / board-stack conduction (full FEA remains a future upgrade). |
| EMC layout compliance checks | `file` | `emc_run_full_compliance` | `partial` | 10.0.x | Presence/heuristic checks with fixed Er (work order K2/K10); EM-result-based, standard-named, fail-capable checks are Phase 3 (P3-T5). |
| DFM manufacturer checks and cost | `file` | `dfm_run_manufacturer_check` | `covered` | 10.0.x | dfm_load_manufacturer_profile, dfm_calculate_manufacturing_cost. |
| SPICE simulation (op / AC / transient / DC sweep) | `cli` | `sim_run_transient` | `covered` | 10.0.x | ngspice engine; sim_run_operating_point/ac_analysis/dc_sweep, sim_check_stability. |
| 2D/3D field / EM solver for impedance & coupling | `file` | `si_get_solver_capabilities` | `partial` | 10.0.x | si_get_solver_capabilities exposes the configured solver seams and explicit solver-unavailable policy. No full field/EM backend is integrated yet; closed-form results remain critic-only and blocked for release signoff unless a solver-grade backend is configured. |

### `export`

Gerber/drill/BOM/POS/STEP/ODB/IPC2581/SVG/PDF/3D manufacturing outputs.

| Capability | Channel | MCP tool | Status | KiCad | Notes |
|---|---|---|---|---|---|
| Gerber export | `cli` | `export_gerber` | `covered` | 10.0.x |  |
| Drill export | `cli` | `export_drill` | `covered` | 10.0.x |  |
| BOM export | `cli` | `export_bom` | `covered` | 10.0.x | export_sch_python_bom for the Python BOM path. |
| Pick-and-place (POS/CPL) export | `cli` | `export_pick_and_place` | `covered` | 10.0.x | mfg_correct_cpl_rotations for fab rotation fixups. |
| STEP / 3D model export | `cli` | `export_step` | `covered` | 10.0.x | export_stepz, export_glb, export_vrml, export_stl, export_ply, export_brep, export_u3d. |
| IPC-2581 / ODB++ interchange export | `cli` | `export_ipc2581` | `covered` | 10.0.x | export_odb. |
| SVG / PDF / DXF documentation export | `cli` | `export_pcb_pdf` | `covered` | 10.0.x | export_sch_pdf, export_svg, export_dxf, export_sch_svg, export_sch_dxf. |
| Netlist export | `cli` | `export_netlist` | `covered` | 10.0.x | export_spice_netlist. |
| Release-gated manufacturing package | `cli` | `export_manufacturing_package` | `covered` | 10.0.x | Hard-gated on project_quality_gate PASS. |

### `project`

Variants, embedded files, jobsets, VCS, and design intent.

| Capability | Channel | MCP tool | Status | KiCad | Notes |
|---|---|---|---|---|---|
| Assembly variants (create / activate / diff / export) | `file` | `variant_create` | `covered` | 10.0.x | variant_set_active, variant_diff_bom, variant_export_bom, variant_clone. |
| Embedded project files | `file` | `project_embed_file` | `covered` | 10.0.x | project_list_embedded_files, project_extract_embedded_file, project_remove_embedded_file. |
| Job sets (export automation) | `cli` | `jobset_export` | `covered` | 10.0.x | jobset_list_templates, jobset_run, jobset_validate. |
| Version-control checkpoints | `file` | `vcs_commit_checkpoint` | `covered` | 10.0.x | vcs_init_git, vcs_list_checkpoints, vcs_restore_checkpoint, vcs_diff_with_checkpoint, vcs_tag_release. |
| Capture / infer design intent and spec | `file` | `project_set_design_intent` | `covered` | 10.0.x | project_get_design_spec, project_infer_design_spec, project_validate_design_spec. |

### `cosmetics`

Silk, board art, drawing sheet / title block, fab notes, fiducials, mounting holes.

| Capability | Channel | MCP tool | Status | KiCad | Notes |
|---|---|---|---|---|---|
| Add silkscreen / fab text | `ipc` | `pcb_add_text` | `covered` | 10.0.x |  |
| Add a barcode / data-matrix | `file` | `pcb_add_barcode` | `covered` | 10.0.x |  |
| Add fiducials | `ipc` | `pcb_add_fiducial_marks` | `covered` | 10.0.x |  |
| Add mounting holes | `ipc` | `pcb_add_mounting_holes` | `covered` | 10.0.x |  |
| Add inner-layer graphics to a footprint | `file` | `add_footprint_inner_layer_graphic` | `covered` | 10.0.x |  |
| Set drawing-sheet title-block fields | `ipc` | `pcb_set_title_block_info` | `covered` | 10.0.x | pcb_set_title_block_info. |
| Import a logo/bitmap as board art (bitmap2component) | `file` | `pcb_add_bitmap_board_art` | `covered` | 10.0.x | pcb_add_bitmap_board_art imports bitmap/logo pixels into deterministic filled board-art rectangles on the requested PCB graphics layer. It intentionally avoids private paths and caps generated shape count for reviewable output. |
| Custom drawing-sheet (.kicad_wks) template design | `gui-only` | — | `gui-only-no-api` | 10.0.x | The page-layout editor is interactive; no headless drawing-sheet authoring surface. |

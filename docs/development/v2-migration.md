# v2 Migration Notes

## Component Search Surface

The v2 library surface removes the legacy browser-URL helpers:

- `lib_get_lcsc_search_url`
- `lib_search_lcsc`

Use the live component tools instead:

- `lib_search_components`
- `lib_get_component_details`
- `lib_assign_lcsc_to_symbol`
- `lib_get_bom_with_pricing`
- `lib_check_stock_availability`
- `lib_find_alternative_parts`

### Default Source

`jlcsearch` is the default live source because it is zero-auth and works in the
standard local profile.

### Optional Sources

`nexar` and `digikey` require external credentials and are intended for
authenticated deployments.

## Simulation Surface

v2 also adds a dedicated SPICE simulation category:

- `sim_run_operating_point`
- `sim_run_ac_analysis`
- `sim_run_transient`
- `sim_run_dc_sweep`
- `sim_check_stability`
- `sim_add_spice_directive`

The preferred backend is `InSpice` when the `simulation` extra is installed.
When that path is unavailable, the server falls back to direct `ngspice` CLI
execution.

## Signal Integrity Surface

v2 adds a signal-integrity category focused on quick transmission-line and
placement checks:

- `si_calculate_trace_impedance`
- `si_calculate_trace_width_for_impedance`
- `si_check_differential_pair_skew`
- `si_validate_length_matching`
- `si_generate_stackup`
- `si_check_via_stub`
- `si_calculate_decoupling_placement`

These tools use quasi-static formulas and board heuristics so agents can make
better placement and routing decisions before a full SI review.

## Power Integrity Surface

v2 also adds a board-focused PDN and thermal review category:

- `pdn_calculate_voltage_drop`
- `pdn_recommend_decoupling_caps`
- `pdn_check_copper_weight`
- `pdn_generate_power_plane`
- `thermal_calculate_via_count`
- `thermal_check_copper_pour`

This surface gives agents a lightweight way to review rail sizing, local
decoupling, copper spreading, and stitched thermal escape plans before final DRC.

## EMC Surface

v2 adds EMC-oriented board heuristics and a bundled sweep:

- `emc_check_ground_plane_voids`
- `emc_check_return_path_continuity`
- `emc_check_split_plane_crossing`
- `emc_check_decoupling_placement`
- `emc_check_via_stitching`
- `emc_check_differential_pair_symmetry`
- `emc_check_high_speed_routing_rules`
- `emc_run_full_compliance`

The bundled compliance sweep runs ten named checks and returns pass/warn/fail
text so agents can surface EMC risk early in the layout cycle.

## PCB Bring-Up Surface

v2 expands the PCB write category with first-layout helpers:

- `pcb_auto_place_by_schematic`
- `pcb_place_decoupling_caps`
- `pcb_group_by_function`
- `pcb_align_footprints`
- `pcb_set_keepout_zone`
- `pcb_add_mounting_holes`
- `pcb_add_fiducial_marks`
- `pcb_add_teardrops`

These tools sit on top of the existing file-based footprint sync flow. They are
meant to accelerate initial board bring-up, cluster related references, add
simple manufacturing markers, and create basic keepout or copper helper shapes
before a manual refinement pass in the KiCad PCB editor.

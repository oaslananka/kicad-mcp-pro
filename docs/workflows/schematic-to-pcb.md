# Schematic To PCB

1. Capture the schematic.
   Author parts with `sch_add_symbol()`, wiring with `sch_add_wire()`, and net names with `sch_add_label()`. Each snaps to the 1.27 mm / 50 mil grid by default; pass `snap_to_grid=False` only for an intentional off-grid coordinate. `sch_add_label()` accepts either `name` or `text` (one is required) and an optional `justify`; `sch_add_symbol()` takes `library`, `symbol_name`, `x_mm`, `y_mm`, `reference`, `value`, and optional `footprint`, `rotation`, `unit`.
   Use `sch_find_free_placement()` before adding new parts when you need collision-free coordinates, and pass `keepout_regions` if parts must stay out of reserved areas.
   Use `sch_get_bounding_boxes()` to inspect occupied sheet regions with pin-aware symbol extents.

   Example — add a resistor, wire it, and name the net on the active root sheet:

   ```text
   sch_add_symbol(library="Device", symbol_name="R",
                  x_mm=63.5, y_mm=76.2, reference="R1", value="10k")
   sch_add_wire(x1_mm=63.5, y1_mm=76.2, x2_mm=76.2, y2_mm=76.2)
   sch_add_label(name="SENSE", x_mm=76.2, y_mm=76.2)
   ```

   Each call writes to the active `.kicad_sch` and returns a result that includes
   a reload confirmation and a `Target schematic (root): <path>` line, plus a snap
   notice when a coordinate moved, an overlap warning when the point is near an
   existing symbol, or a footprint warning when no footprint is set. The symbol
   call needs `library`, `symbol_name`, `x_mm`, `y_mm`, `reference`, and `value`;
   all other arguments are optional. The label call needs `name` or `text`.
2. Assign footprints.
   Resolve real, sourceable parts before assigning: search the live catalog with `lib_search_components()`, inspect a match with `lib_get_component_details()`, then bind it with `lib_bind_part_to_symbol()` (or `lib_assign_footprint()` for a footprint-only property). Check availability with `lib_check_stock_availability()` and policy/derating with `lib_check_sourcing_policy()` and `lib_check_derating()`. When a footprint is not in a library, generate one with `lib_generate_footprint_ipc7351()` and validate it with `lib_validate_footprint_ipc7351()`.
3. Export a netlist.
   If the schematic needs cleanup first, run `sch_auto_place_functional()` to group connectors, MCU blocks, sensors, and UI parts. Set `anchor_ref` to keep already-reviewed symbols fixed, and tune inter-group spacing with `project_set_design_intent(functional_spacing_mm=...)`.
   Use `sch_get_template_info()` to inspect bundled subcircuit templates, including their declared left/right pin lists, before instantiating them.
4. Place footprints and route.
   Use `pcb_auto_place_force_directed()` for a headless spring-layout pass when you want a deterministic starting point before manual polish. Stopping is convergence-based — not wall-clock — so the same inputs yield bit-for-bit identical placement on any machine; the result reports `iterations_run`, `converged`, and `max_displacement_mm`. The tool supports `keepout_regions` and `grid_mm`, and exposes `max_seconds` only as an opt-in safety valve (default `0` = disabled, deterministic) for pathologically large boards.
   Review `pcb_score_placement()` after placement; it now reports critical-net Manhattan proxy length and thermal-hotspot proximity in addition to the existing intent-aware checks.
   For external autorouting, stage DSN/SES with `route_export_dsn()`, `route_autoroute_freerouting()`, and `route_import_ses()`. FreeRouting runs Docker-first when available using the pinned `ghcr.io/freerouting/freerouting:2.1.0` image, falls back to a configured JAR, and reports routed percentage, pass count, wall time, and stdout tail.
   `route_autoroute_freerouting()` defaults are `dsn_path="output/routing/board.dsn"`, `ses_path="output/routing/board.ses"`, `max_passes=100`, `thread_count=4`, `use_docker=True`, and `drc_report_path="output/routing/freerouting.drc.json"`; narrow the netlist with `net_classes_to_ignore` and `exclude_nets`, or point at a specific router with `freerouting_jar_path`. KiCad has no headless SES import, so the tool returns `human_gate_required=True` and does not claim the board is routed until the session is applied. Use `route_apply_ses()` to apply the session headlessly (deterministic and idempotent) or follow the surfaced File > Import > Specctra Session step, then run `run_drc()` to verify.
   Transfer schematic changes onto the board with `pcb_sync_from_schematic()`. It runs the pre-sync gate by default and blocks a dirty schematic transfer; use `force=True` only for known-bad intermediate states. Placement outcome is controlled by `origin_x_mm`/`origin_y_mm` (default `20.0`), `grid_mm` (default `2.54`), and `auto_place` (default `True`); `replace_mismatched=True` replaces an existing footprint whose reference no longer matches its assigned footprint name.
5. Validate and export.
   Run ERC and DRC with `run_erc()` and `run_drc()` (both accept `save_report=True` to persist the JSON report). `validate_design()` runs both and returns a summary of DRC violations, unconnected items, and ERC violations. For the full gated check, use `project_quality_gate()` and `project_full_validation_loop()` before exporting.

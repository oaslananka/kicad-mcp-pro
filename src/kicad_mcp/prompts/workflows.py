"""Prompt templates for common KiCad workflows."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP
from mcp.types import TextContent


def render_professional_circuit_design_prompt(
    *,
    circuit_description: str = "",
    board_size_mm: str = "100x80",
    layer_count: str = "2",
    target_fab: str = "jlcpcb_standard",
    design_notes: str = "",
) -> str:
    """Render the canonical professional circuit design workflow prompt."""
    notes = f"\n\nDesign intent summary:\n{design_notes.strip()}" if design_notes.strip() else ""
    return f"""
# Professional Circuit Design Workflow

Circuit: {circuit_description or "(not specified)"}
Board: {board_size_mm} mm, {layer_count} copper layer(s), target fab {target_fab}

1. Project setup:
   - `kicad_get_version()`
   - `kicad_create_new_project()` or `kicad_set_project()`
   - `project_set_design_intent()` before schematic work
   - Read `kicad://project/info`
2. Schematic capture:
   - Use `sch_find_free_placement()` before placing symbols
   - Add power symbols before dependent circuits
   - Route wires, then call `sch_add_missing_junctions()`
   - Run `sch_check_power_flags()` and `run_erc()`
   - Run `schematic_design_rule_check()` and resolve advisory findings
     (decoupling caps, I2C/reset pull-ups, crystal load caps)
   - Run `sch_visual_qa()` then `sch_fix_readability()` to clear text overlap,
     off-sheet symbols, and unconnected symbol overlap (readability critic)
3. PCB transfer and placement:
   - `pcb_set_board_outline()`
   - `pcb_sync_from_schematic()`; the pre-sync gate blocks dirty schematics
   - `pcb_auto_place_force_directed()` or the automatic sync placement result
   - `pcb_place_decoupling_caps()`
   - `pcb_visual_qa()` then `pcb_fix_readability()` to clear overlapping
     reference designators and flag any off-board parts
4. Routing:
   - `route_export_dsn()`
   - `route_autoroute_freerouting()`
   - `route_import_ses()`
   - `pcb_refill_zones()`
5. Validation and release:
   - `project_full_validation_loop(max_iterations=5)`
   - `pcb_score_placement()`
   - `check_design_for_manufacture(profile="{target_fab}")`
   - `export_manufacturing_package()` only after `project_quality_gate()` is PASS

Do not skip a stage. If a gate fails, read `kicad://project/fix_queue`, apply the
first recommended fix, and rerun the relevant gate.{notes}
""".strip()


def register(mcp: FastMCP) -> None:
    """Register reusable workflow prompts."""

    @mcp.prompt()
    def first_pcb(
        component_count: str = "10",
        board_size_mm: str = "50x50",
        layers: str = "2",
    ) -> list[TextContent]:
        """Guide an agent through a first-board workflow."""
        text = f"""
Design a new KiCad PCB with approximately {component_count} components, a board size of
{board_size_mm} mm, and {layers} copper layers.

Workflow:
1. Call `kicad_get_version()`.
2. Call `kicad_set_project()` or `kicad_create_new_project()`.
3. Review `kicad://project/info` and `kicad://board/summary`.
4. Define the outline with `pcb_set_board_outline()`.
5. Populate the schematic using the schematic and library tools.
6. Run `run_erc()` and `schematic_design_rule_check()`, then fix issues before layout.
7. Route with PCB tools.
8. Run `run_drc()` and `check_design_for_manufacture()`.
9. Export a manufacturing package.
""".strip()
        return [TextContent(type="text", text=text)]

    @mcp.prompt()
    def schematic_to_pcb() -> list[TextContent]:
        """Guide an agent from schematic capture to PCB layout."""
        text = """
Move a design from schematic capture to PCB layout.

1. Inspect the active project and schematic.
2. Add or update symbols, labels, buses, and power flags.
3. Run ERC, power checks, and `schematic_design_rule_check()` (electrical-correctness critic).
4. Run `sch_visual_qa()` and `sch_fix_readability()` (readability critic: text overlap, off-sheet).
5. Export the netlist.
6. Inspect footprints and assign missing ones.
7. Move footprints, then run `pcb_visual_qa()` and `pcb_fix_readability()` to clear
   overlapping reference designators, then run the post-placement routing pass
   (apply the routed session in KiCad when the tool surfaces the manual import step):
   a. `route_export_dsn()`
   b. `route_autoroute_freerouting()` — Docker-first, JAR fallback
   c. `route_import_ses()`
   d. `pcb_refill_zones()`
   e. `run_drc()`
8. Compare PCB versus schematic footprints.
""".strip()
        return [TextContent(type="text", text=text)]

    @mcp.prompt()
    def professional_circuit_design(
        circuit_description: str = "",
        board_size_mm: str = "100x80",
        layer_count: str = "2",
        target_fab: str = "jlcpcb_standard",
    ) -> list[TextContent]:
        """Canonical workflow for a complete professional circuit design."""
        text = render_professional_circuit_design_prompt(
            circuit_description=circuit_description,
            board_size_mm=board_size_mm,
            layer_count=layer_count,
            target_fab=target_fab,
        )
        return [TextContent(type="text", text=text)]

    @mcp.prompt()
    def post_placement_routing() -> list[TextContent]:
        """Route a placed PCB through DSN, FreeRouting, SES import, and DRC."""
        text = """
Run the mandatory post-placement routing loop.

1. Confirm placement is acceptable with `pcb_score_placement()`.
2. Export routing input with `route_export_dsn()`.
3. Run `route_autoroute_freerouting()` after placement; it routes headlessly and
   surfaces the KiCad import step (`human_gate_required`) when the SES must be applied.
4. Apply the routed result with `route_import_ses()`, then perform the KiCad GUI
   import it describes.
5. Refill copper with `pcb_refill_zones()`.
6. Run `run_drc()` and inspect `kicad://project/fix_queue`.
7. Repeat only the failing step; do not restart schematic capture unless the transfer gate fails.
""".strip()
        return [TextContent(type="text", text=text)]

    @mcp.prompt()
    def manufacturing_export() -> list[TextContent]:
        """Checklist for manufacturing exports."""
        text = """
Run a manufacturing release pass. Treat `export_manufacturing_package()` as a release
step, not a debugging shortcut. In the `manufacturing` profile it is the only gated
manufacturing export tool.

1. `project_quality_gate()`
2. If the gate is not `PASS`, stop and fix the blocking issues first.
3. `pcb_transfer_quality_gate()`
4. `run_drc()`
5. `run_erc()`
6. `get_board_stats()`
7. `check_design_for_manufacture()`
8. If you need low-level debug or interchange artifacts, switch to a broader profile
   such as `full` or `minimal` and use the direct `export_*()` tools there.
9. Only after a clean gate, call `export_manufacturing_package()`.
""".strip()
        return [TextContent(type="text", text=text)]

    @mcp.prompt()
    def design_review_loop() -> list[TextContent]:
        """Closed-loop inspection workflow driven by quality gates."""
        text = """
Run a closed-loop design review instead of trusting a single build pass.

1. Inspect the current context:
   - `kicad://project/info`
   - `kicad://project/spec`
   - `kicad://project/quality_gate`
   - `kicad://project/fix_queue`
   - `kicad://project/next_action`
   - `kicad://schematic/connectivity`
   - `kicad://board/placement_quality`
   - `project_get_design_spec()`
2. Call the blocking gate tools directly when you need fresh detail:
   - `project_quality_gate()`
   - `project_quality_gate_report()`
   - `schematic_connectivity_gate()`
   - `pcb_transfer_quality_gate()`
   - `pcb_score_placement()`
   - `pcb_placement_quality_report()`
   - `sch_visual_qa()` / `pcb_visual_qa()` (readability: overlap, off-sheet, silk)
3. Fix the highest-severity blocking issue first. For advisory readability findings
   run `sch_fix_readability()` / `pcb_fix_readability()`.
4. Re-run the relevant gates after every fix.
5. Repeat until the full project gate is `PASS`.
6. Only then move on to release exports.
""".strip()
        return [TextContent(type="text", text=text)]

    @mcp.prompt()
    def visual_excellence_loop() -> list[TextContent]:
        """Score → fix → render → verify loop for professional schematic cosmetics."""
        text = """
Drive the schematic to a professional, cosmetically clean state with a measured
loop. Cosmetic fixers keep electrical connectivity as a hard invariant, so apply
them without fear — but verify the render and finish with ERC.

Run this loop per sheet until the score meets the target (default 80/100) or no
fixer applies:

1. Measure with `sch_cosmetic_score()`. If the score is at target, stop. Else
   read `worst_category`.
2. Dry-run the matching fixer (default `apply=false`) and read
   `connectivity_preserved`:
   - `grid` -> `sch_align_to_grid()`
   - `wiring` -> `sch_straighten_wires()`
   - `readability` -> `sch_resolve_label_overlaps()`
   - `orientation` -> `sch_normalize_power_orientation()`
   - `typography` -> `sch_normalize_text_sizes()`
3. If `connectivity_preserved` is false, do not apply — the fix would change a
   net; surface it for a human. If true, apply with `apply=true`.
4. See it: `sch_render_png()`, then `sch_render_visual_diff()` to confirm the
   delta covers only the objects you intended to move.
5. Re-measure with `sch_cosmetic_score()`; confirm the score rose. Repeat.
6. When every applicable fixer reports `no_change`, stop even if below target —
   the rest needs human layout judgment. Report what is left.
7. Finish with `run_erc()`: a clean cosmetic pass must also be electrically
   clean. Cosmetic checks never substitute for ERC or human approval.
""".strip()
        return [TextContent(type="text", text=text)]

    @mcp.prompt()
    def fix_blocking_issues() -> list[TextContent]:
        """Prompt focused on consuming the fix queue and clearing blockers."""
        text = """
Use the project fix queue as the source of truth for what to fix next.

1. Read `kicad://project/fix_queue`.
2. Read `kicad://project/next_action`.
3. Pick the first blocking item unless `project_get_next_action()` surfaces
   a higher-priority blocker.
4. Use the suggested tool on that line to inspect or repair the issue.
5. If the blocker is spec-aware, refresh `project_get_design_spec()` or update it with
   `project_set_design_intent()`, then verify with `project_validate_design_spec()`
   before moving footprints again.
6. Re-run `project_quality_gate()` after the fix.
7. Stop only when the queue says there are no blocking issues left.
""".strip()
        return [TextContent(type="text", text=text)]

    @mcp.prompt()
    def error_recovery() -> list[TextContent]:
        """How to read structured errors and retry safely (idempotency contract)."""
        text = """
When a tool call fails, read the structured error payload before retrying.

Every error carries: code, message, hint, retryable, transient_class, retry_after_ms.

1. If `retryable` is false, do not retry the same call. Fix the request or
   configuration using `hint`, then proceed.
2. If `retryable` is true, branch on `transient_class`:
   - `network` / `timeout` / `lock`: a transient fault. Wait `retry_after_ms`
     (or a short backoff) and retry — but ONLY if the tool is idempotent
     (annotation `idempotentHint: true`). Re-calling a non-idempotent write can
     double-apply (e.g. a second track, via, or symbol).
   - `state`: a precondition is unmet (e.g. no board open). Reconcile first
     (open the board / set the project), then retry. Retrying alone will not help.
3. For a non-idempotent tool after a transient error, reconcile-then-retry: read
   current state (e.g. `pcb_get_board_summary()`, `sch_get_symbols()`) to check
   whether the operation already applied before calling it again.
4. Read-only tools and converging writes (set_/save/refill/export/upgrade) are
   idempotent; additive writes (add_/create_/place_/route_/build_) are not.
""".strip()
        return [TextContent(type="text", text=text)]

    @mcp.prompt()
    def manufacturing_release_checklist() -> list[TextContent]:
        """Final release checklist for fab-ready handoff."""
        text = """
Treat manufacturing release as a gated handoff.

1. Read `kicad://project/quality_gate`.
2. If the project gate is not `PASS`, stop immediately and clear blockers.
3. Read `kicad://project/fix_queue` to confirm nothing actionable remains.
4. Re-run:
   - `project_quality_gate()`
   - `pcb_transfer_quality_gate()`
   - `run_drc()`
   - `run_erc()`
   - `check_design_for_manufacture()`
5. If you need low-level debug artifacts, switch to a broader profile such as `full`
   or `minimal`; the `manufacturing` profile stays focused on gated release handoff.
6. Release with `export_manufacturing_package()` only after every gate is clean.
""".strip()
        return [TextContent(type="text", text=text)]

    @mcp.prompt()
    def high_speed_review_loop() -> list[TextContent]:
        """Agent loop for SI, stackup, routing, and high-speed checkpoint review."""
        text = """
Run a high-speed review loop for critical nets.

1. Read `kicad://project/design_intent` and confirm `critical_nets`.
2. Run `pcb_get_stackup()` and check dielectric/copper assumptions.
3. Run `route_tune_time_domain()` for each timing-critical net.
4. Run `si_check_via_stub()` and look for critical-frequency resonance warnings.
5. Run `emc_check_return_path_continuity(reference_plane_layer="auto")`.
6. Re-route or add stitching vias where the return path is weak.
7. Run `route_autoroute_freerouting()` only when DSN/SES staging is ready.
8. Re-check SI/EMC and create a `vcs_commit_checkpoint()` when the board improves.
""".strip()
        return [TextContent(type="text", text=text)]

    @mcp.prompt()
    def new_board_bringup() -> list[TextContent]:
        """Agent loop for starting a new board from schematic through first DRC."""
        text = """
Bring up a new board in small reversible steps.

1. Set or create the project with `kicad_set_project()` / `kicad_create_new_project()`.
2. Capture or import the schematic and run `run_erc()`.
3. Assign footprints and verify `validate_footprints_vs_schematic()`.
4. Define board outline, stackup, and basic design rules.
5. Run `pcb_auto_place_by_schematic()` and inspect `pcb_score_placement()`.
6. Route critical nets first, refill zones, and run `run_drc()`.
7. Commit checkpoints after every clean gate.
""".strip()
        return [TextContent(type="text", text=text)]

    @mcp.prompt()
    def dfm_polish_loop() -> list[TextContent]:
        """Agent loop for manufacturer-specific DFM cleanup."""
        text = """
Polish the design against a manufacturer profile.

1. Load the target profile with `dfm_load_manufacturer_profile()`.
2. Run `dfm_run_manufacturer_check()` and `project_quality_gate()`.
3. Fix hard blockers first: trace/space, drill, annular ring, silk, courtyard.
4. Re-run DFM after each fix and read `kicad://project/fix_queue`.
5. Stop for human review if a warning requires a fab-specific decision.
6. Export only with `export_manufacturing_package()` after the gates pass.
""".strip()
        return [TextContent(type="text", text=text)]

    @mcp.prompt()
    def regression_sweep() -> list[TextContent]:
        """CI-style prompt for repeatable ERC, DRC, and quality-gate regression checks."""
        text = """
Run a repeatable project regression sweep.

1. Read `kicad://project/manifest` to capture the file/hash baseline.
2. Run `run_erc()` and `run_drc()`.
3. Run `project_quality_gate()` and `project_quality_gate_report()`.
4. Read `kicad://project/gate_history` and compare current outcomes.
5. Report any new FAIL/BLOCKED gate before release work continues.
""".strip()
        return [TextContent(type="text", text=text)]

    # ── Spec-requested named prompts ──────────────────────────────────────

    @mcp.prompt()
    def kicad_review_board() -> list[TextContent]:
        """Perform a structured board review covering DRC, stackup, placement, and SI."""
        text = """
Run a structured PCB design review.

1. Read `kicad://project/info` and `kicad://board/summary` for context.
2. Run `run_drc()` and inspect `kicad://drc/latest` for violations.
3. Read `kicad://board/placement_quality` for placement score.
4. Read `kicad://board/layer_coverage` for copper distribution.
5. Check `kicad://analysis/stackup` for layer stack assumptions.
6. Run `pcb_score_placement()` for placement quality metric.
7. Inspect `pcb_get_nets()` for net classification.
8. Read `kicad://project/quality_gate` for overall gate status.
9. Summarize findings: pass/fail per category, top issues, recommended fixes.
10. If `kicad://project/fix_queue` has blockers, escalate highest-priority items.
""".strip()
        return [TextContent(type="text", text=text)]

    @mcp.prompt()
    def kicad_fix_erc() -> list[TextContent]:
        """Systematic approach to resolve ERC violations in the schematic."""
        text = """
Fix Electrical Rule Check (ERC) violations systematically.

1. Run `run_erc(save_report=True)` and read `kicad://erc/latest`.
2. Group violations by severity and type.
3. For each violation:
   a. Identify the affected nets, symbols, or pins using `sch_trace_net()`.
   b. Fix the root cause: wire, label, power flag, pin mismatch, or missing junction.
   c. If a rule needs adjustment, use `erc_set_rule_severity()`.
4. Re-run `run_erc()` after each fix.
5. Repeat until ERC shows zero violations.
6. If the fix queue suggests a specific order, follow it.
""".strip()
        return [TextContent(type="text", text=text)]

    @mcp.prompt()
    def kicad_fix_drc() -> list[TextContent]:
        """Systematic approach to resolve DRC violations in the PCB layout."""
        text = """
Fix Design Rule Check (DRC) violations systematically.

1. Run `run_drc(save_report=True)` and read `kicad://drc/latest`.
2. Inspect `drc_list_rules()` and `drc_list_exclusions()` for current configuration.
3. For each violation:
   a. Identify the affected nets/footprints using `pcb_get_nets()`.
   b. Fix: adjust track width/clearance, move footprints, add vias, re-route.
   c. For false positives, add `drc_add_exclusion()`.
4. Re-run `run_drc()` after each fix.
5. If design rules need adjustment, use `pcb_set_design_rules()` or `drc_rule_create()`.
6. Repeat until DRC shows zero violations.
7. Run `pcb_refill_zones()` before final DRC.
""".strip()
        return [TextContent(type="text", text=text)]

    @mcp.prompt()
    def kicad_prepare_manufacturing() -> list[TextContent]:
        """Complete manufacturing release preparation workflow."""
        text = """
Prepare the complete manufacturing release package.

1. Read `kicad://manufacturing/checklist` for the full checklist.
2. Verify all pre-release gates:
   - `project_quality_gate()` == PASS
   - `pcb_transfer_quality_gate()` == PASS
   - `run_drc()` — zero violations
   - `run_erc()` — zero violations
   - `check_design_for_manufacture()` — PASS
3. If any gate fails, fix before proceeding.
4. Load manufacturer profile: `dfm_load_manufacturer_profile()`.
5. Run DFM: `dfm_run_manufacturer_check()`.
6. Export manufacturing outputs:
   - `export_gerber()`, `export_drill()`
   - `export_pick_and_place()`, `export_bom()`
   - `export_3d_step()`, `export_pcb_pdf()`
7. Generate release manifest: `mfg_generate_release_manifest()`.
8. Correct CPL rotations: `mfg_correct_cpl_rotations()`.
9. Tag the release: `vcs_tag_release(tag, message)`.
10. Call `export_manufacturing_package()` for the final zip.
""".strip()
        return [TextContent(type="text", text=text)]

    @mcp.prompt()
    def kicad_high_speed_review() -> list[TextContent]:
        """High-speed design review for SI, EMC, and signal integrity."""
        text = """
Perform a high-speed design review.

1. Read `kicad://analysis/stackup` and `kicad://analysis/materials` for stackup context.
2. Run `si_list_dielectric_materials()` and `si_generate_stackup()`.
3. Identify critical nets from design intent `project_get_design_spec()`.
4. For each critical net:
   a. `si_calculate_trace_impedance()` — verify target impedance.
   b. `si_check_differential_pair_skew()` — verify skew tolerance.
   c. `si_check_via_stub()` — check via stub resonance.
5. Run EMC checks:
   - `emc_check_return_path_continuity()`
   - `emc_check_decoupling_placement()`
   - `emc_check_split_plane_crossing()`
   - `emc_check_via_stitching()`
6. Run power integrity: `check_power_integrity()`.
7. Fix issues and re-run affected checks.
8. Read `pcb_get_stackup()` to verify stackup matches requirements.
""".strip()
        return [TextContent(type="text", text=text)]

    @mcp.prompt()
    def kicad_generate_bom_strategy() -> list[TextContent]:
        """BOM generation, pricing, and sourcing strategy."""
        text = """
Generate and optimize the Bill of Materials.

1. Run `export_bom()` for the base BOM.
2. For each critical component:
   a. `lib_get_component_details()` — verify specs.
   b. `lib_check_stock_availability()` — check stock.
   c. `lib_get_bom_with_pricing()` — get pricing.
   d. `lib_find_alternative_parts()` — find alternatives.
3. Assign LCSC codes: `lib_assign_lcsc_to_symbol()`.
4. Generate variant BOMs if needed: `variant_export_bom()`.
5. Compare variants: `variant_diff_bom()`.
6. Read `kicad://project/manifest` to track all BOM output files.
7. Generate report with pricing, alternatives, and stock status.
""".strip()
        return [TextContent(type="text", text=text)]

    @mcp.prompt()
    def kicad_component_placement_review() -> list[TextContent]:
        """Review and optimize component placement quality."""
        text = """
Review component placement quality.

1. Read `kicad://board/placement_quality` for current score.
2. Run `pcb_score_placement()` for detailed metrics.
3. Run `pcb_placement_quality_gate()` for pass/fail gate.
4. Identify issues:
   - Read `pcb_get_footprints()` to inspect placed footprints.
   - Use `pcb_get_net_statistics()` for net density.
5. Optimize:
   - `pcb_place_decoupling_caps()` — place decoupling near ICs.
   - `pcb_align_footprints()` — align components.
   - `pcb_group_by_function()` — group related parts.
6. Re-score after each optimization.
7. Run `pcb_check_creepage_clearance()` for safety clearance.
8. Target score >= 80 before proceeding to routing.
""".strip()
        return [TextContent(type="text", text=text)]

    @mcp.prompt()
    def kicad_route_diff_pair() -> list[TextContent]:
        """Route differential pair nets with impedance and skew control."""
        text = """
Route a differential pair with proper impedance and skew control.

1. Identify the differential pair nets from `project_get_design_spec()`.
2. Run `si_calculate_trace_width_for_impedance()` for target geometry.
3. Create a tuning profile: `route_create_tuning_profile()`.
4. Route the pair: `route_differential_pair()`.
5. Check skew: `si_check_differential_pair_skew()`.
6. Tune length: `route_tune_length()`.
7. Apply tuning profile: `route_apply_tuning_profile()`.
8. Fine-tune differential length: `tune_diff_pair_length()`.
9. Run `run_drc()` to verify clearance.
10. Read `pcb_get_impedance_for_trace()` to verify impedance.
""".strip()
        return [TextContent(type="text", text=text)]

    @mcp.prompt()
    def kicad_simulation_plan() -> list[TextContent]:
        """Plan and run SPICE simulations for circuit verification."""
        text = """
Plan and run SPICE simulations.

1. Export spice netlist: `export_spice_netlist()`.
2. List available libraries: `sim_list_spice_libraries()`.
3. If models are needed:
   a. `sim_add_spice_library()` to add required models.
   b. `sim_assign_spice_model()` to assign to components.
4. Validate the setup: `sim_validate_spice_setup()`.
5. Run simulations:
   a. `sim_run_operating_point()` — DC bias analysis.
   b. `sim_run_ac_analysis()` — frequency response.
   c. `sim_run_transient()` — time domain response.
   d. `sim_run_dc_sweep()` — DC sweep.
6. Check stability: `sim_check_stability()`.
7. Add directives as needed: `sim_add_spice_directive()`.
8. Document results for each simulation type.
""".strip()
        return [TextContent(type="text", text=text)]

---
name: schematic-review
description: KiCad MCP schematic inspection and review workflow using ERC, connectivity, symbol, net, power, readability, and quality-gate tools.
---

# Schematic Review Skill

Use this skill when an AI agent is asked to inspect, review, or safely improve a KiCad schematic through KiCad MCP Pro.

This skill is specific to `oaslananka/kicad-mcp-pro` and should be kept synchronized with `docs/tools-reference.generated.md`.

## When to use

Use this skill for:

- Pre-layout schematic review
- ERC review
- Net connectivity review
- Power flag and no-connect review
- Symbol, footprint, and component-property inspection
- Readability and visual QA
- Conservative schematic edits when explicitly requested

Do not use this skill to claim electrical correctness without ERC, design-rule review, datasheet review, and human engineering approval.

## Required context

Collect:

- Active project path and schematic file
- Design intent and functional requirements
- Expected power rails, interfaces, and critical nets
- Component sourcing assumptions
- Whether the task is read-only review or allowed to modify the schematic

## Primary MCP tools

### Project and intent

- `kicad_get_project_info`
- `project_get_design_intent`
- `project_set_design_intent`
- `project_get_design_spec`
- `project_import_design_spec`
- `project_design_report`

### Read-only schematic inspection

- `sch_get_symbols`
- `sch_get_net_names`
- `sch_get_labels`
- `sch_get_wires`
- `sch_get_connectivity_graph`
- `sch_get_circuit_ir`
- `sch_trace_net`
- `sch_check_power_flags`
- `sch_get_population_status`
- `lib_get_symbol_info`
- `lib_get_footprint_info`
- `lib_verify_component_contract`

### ERC, quality, and visual checks

- `run_erc`
- `schematic_quality_gate`
- `schematic_connectivity_gate`
- `schematic_design_rule_check`
- `sch_visual_qa`
- `sch_render_png`
- `project_quality_gate`

### Controlled schematic edit tools

Use only when explicitly requested and when the workflow is allowed to modify files.

- `sch_add_symbol`
- `sch_add_component`
- `sch_add_wire`
- `sch_add_label`
- `sch_add_global_label`
- `sch_add_power_symbol`
- `sch_add_no_connect`
- `sch_add_missing_junctions`
- `sch_modify_property`
- `sch_update_properties`
- `sch_move_symbol`
- `sch_delete_symbol`
- `sch_plan_from_spec`
- `sch_preview_plan`
- `sch_apply_plan`
- `sch_verify_plan`
- `sch_rollback_plan`
- `sch_reload`

## Workflow

1. Confirm active project and schematic state with `kicad_get_project_info`.
2. Retrieve design intent with `project_get_design_intent`; if absent and the user supplied requirements, store them with `project_set_design_intent` only when appropriate.
3. Inspect symbols, nets, labels, wires, and connectivity graph.
4. Run ERC with `run_erc`.
5. Run `schematic_quality_gate`, `schematic_connectivity_gate`, and `schematic_design_rule_check`.
6. Check power-rail intent using `sch_check_power_flags` and net tracing for critical rails/interfaces.
7. Check component metadata and footprint bindings with library tools when part correctness is in scope.
8. For readability review, use `sch_visual_qa` and optionally `sch_render_png`.
9. If edits are requested, prefer plan/preview/apply/verify/rollback tools over direct mutation when possible.
10. Re-run ERC and schematic quality gates after any schematic-changing operation.

## Quality checks

A schematic review response must include:

- Project and schematic context
- ERC summary
- Connectivity findings
- Power-flag/no-connect findings
- Symbol/footprint/property findings
- Readability findings
- Required fixes and open questions
- Human-review notes

## Failure modes

Stop and report clearly when:

- No KiCad project is active
- Schematic files are missing or unsupported
- ERC cannot run
- The design intent is too ambiguous to judge correctness
- Component datasheets or footprint requirements are unavailable
- The user requests edits without permission to modify files

## Output format

Return:

- Schematic context
- Tools used
- Findings by severity
- ERC and quality-gate status
- Proposed or applied fixes
- Remaining assumptions
- Next validation steps

## Safety rule

A clean ERC result is necessary but not sufficient for design approval. Always report datasheet, footprint, power-budget, signal-integrity, and human-review gaps separately.

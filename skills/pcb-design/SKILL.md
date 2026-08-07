---
name: pcb-design
description: Safe KiCad PCB design assistance workflow using KiCad MCP board inspection, placement, routing, stackup, and quality-gate tools.
---

# PCB Design Skill

Use this skill when an AI agent is asked to inspect, plan, improve, or safely assist with a KiCad PCB layout through KiCad MCP Pro.

This skill is specific to `oaslananka/kicad-mcp-pro` and should be kept synchronized with `docs/tools-reference.generated.md`.

## When to use

Use this skill for:

- PCB layout review
- Board outline, stackup, and design-rule planning
- Component placement assistance
- Routing-quality review
- Schematic-to-PCB synchronization review
- First-pass power, signal, EMC, and manufacturability sanity checks

Do not use this skill to claim that a board is production-ready. Production readiness requires ERC, DRC, DFM, release package review, and human engineering approval.

## Required context

Collect or establish:

- Active project path with `kicad_set_project` or current state from `kicad_get_project_info`
- Board file and schematic file presence
- Design intent from `project_get_design_intent` or `project_set_design_intent`
- Board constraints: layer count, stackup, clearances, current, voltage, impedance, and manufacturer limits
- User permission before any write/destructive board operation

## Primary MCP tools

### Project and intent

- `kicad_get_project_info`
- `kicad_set_project`
- `project_get_design_intent`
- `project_set_design_intent`
- `project_design_workflow`
- `project_get_next_action`

### Read-only PCB inspection

- `pcb_get_board_summary`
- `pcb_get_layers`
- `pcb_get_stackup`
- `pcb_get_design_rules`
- `pcb_get_footprints`
- `pcb_get_nets`
- `pcb_get_net_statistics`
- `pcb_get_tracks`
- `pcb_get_vias`
- `pcb_get_zones`
- `pcb_get_ratsnest`
- `pcb_net_inspector`

### PCB modification tools

Use only after explaining the planned change and confirming that the workflow is allowed to modify files.

- `pcb_set_board_outline`
- `pcb_set_stackup`
- `pcb_set_design_rules`
- `pcb_sync_from_schematic`
- `pcb_auto_place_by_schematic`
- `pcb_auto_place_force_directed`
- `pcb_move_footprint`
- `pcb_place_component`
- `pcb_place_decoupling_caps`
- `pcb_add_track`
- `pcb_add_tracks_bulk`
- `pcb_add_via`
- `pcb_add_zone`
- `pcb_delete_items`
- `pcb_delete_object`
- `pcb_refill_zones`
- `pcb_save`

### MCP-first mutation boundary

- Prefer `kicad_set_project` over a shell `cd` when the goal is to select the active KiCad project.
- Use dedicated MCP operations for KiCad objects. For example, inspect tracks/vias through MCP, remove existing PCB objects with `pcb_delete_items` or `pcb_delete_object`, and verify with `run_drc`.
- Do **not** rewrite `.kicad_pcb` or `.kicad_sch` with `sed`, regex-based Python, or other ad-hoc text mutation as a fallback when a required MCP tool is unavailable.
- If the current profile or operating mode does not expose the required MCP operation, stop and report the missing tool plus the required profile/mode. Let the user explicitly opt into a broader supported MCP surface instead of silently switching to shell mutation.

### Quality gates and specialist checks

- `pcb_quality_gate`
- `pcb_placement_quality_gate`
- `pcb_transfer_quality_gate`
- `pcb_stackup_consistency_gate`
- `pcb_route_corner_style_gate`
- `pcb_visual_qa`
- `run_drc`
- `check_design_for_manufacture`
- `manufacturing_quality_gate`
- `project_quality_gate`
- `project_revalidate_after_edit`

## Workflow

1. Inspect project state with `kicad_get_project_info`.
2. If needed, set the active project with `kicad_set_project`.
3. Load or define design intent with `project_get_design_intent` or `project_set_design_intent`.
4. Inspect board structure with `pcb_get_board_summary`, `pcb_get_layers`, `pcb_get_stackup`, and `pcb_get_design_rules`.
5. Inspect physical implementation with `pcb_get_footprints`, `pcb_get_nets`, `pcb_get_tracks`, `pcb_get_vias`, and `pcb_get_zones`.
6. For placement tasks, use `pcb_critique_placement`, `pcb_score_placement`, and `pcb_placement_quality_gate` before proposing edits.
7. For routing tasks, inspect ratsnest, tracks, vias, net classes, stackup, and constraints before proposing route changes.
8. Apply write operations only when the requested workflow explicitly allows file changes.
9. Re-run targeted gates after every meaningful edit: `run_drc`, `pcb_quality_gate`, `pcb_transfer_quality_gate`, and `project_revalidate_after_edit`.
10. Produce a report that separates verified tool output, assumptions, changes made, and remaining risks.

## Quality checks

A useful PCB design response must include:

- Active project and board file summary
- Constraints and assumptions used
- Read-only observations before any mutation
- List of write operations, if any
- DRC and quality-gate result summary
- Remaining warnings, unknowns, and required human checks

## Failure modes

Stop and report clearly when:

- No KiCad project is active
- The board file is missing or not parseable
- Required KiCad CLI/IPC capability is unavailable
- A required MCP mutation tool is unavailable in the active profile/mode; report the required profile/mode instead of falling back to raw KiCad-file mutation
- The user requested write operations but no safe project context exists
- DRC or quality-gate output is missing after a layout-changing operation
- The board depends on manufacturer constraints that were not provided

## Output format

Return:

- Project context
- Tools used
- Findings by severity
- Changes made or proposed
- Validation results
- Manufacturing readiness status: `not assessed`, `blocked`, `needs review`, or `candidate after human review`
- Next actions

## Safety rule

Never state that a PCB is ready for fabrication solely because edits were applied. Fabrication output requires the fabrication-output workflow and qualified human review.

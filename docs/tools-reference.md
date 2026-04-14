# Tools Reference

See the README for the complete tool list.

Recommended startup flow:

1. `kicad_get_version()`
2. `kicad_set_project()`
3. `kicad_list_tool_categories()`
4. Inspect resources such as `kicad://project/info`

## Release-Critical Tools

For agent-driven design work, these tools form the minimum safe review loop:

- `project_quality_gate()`
- `schematic_connectivity_gate()`
- `pcb_placement_quality_gate()`
- `pcb_transfer_quality_gate()`
- `pcb_score_placement()`
- `manufacturing_quality_gate()`
- `validate_footprints_vs_schematic()`

`export_manufacturing_package()` is a release-only tool and hard-blocks unless the
full project gate is `PASS`.

## Design Intent Tools

These tools persist the engineering assumptions that intent-aware placement checks use:

- `project_set_design_intent()`
- `project_get_design_intent()`

Current intent fields:

- connector references
- decoupling pairs
- critical nets
- power-tree references
- analog references
- digital references
- sensor-cluster references
- RF keepout regions
- manufacturer / manufacturer tier

## Critic Resources

The MCP resource surface mirrors the current review state so an agent can iterate safely:

- `kicad://project/quality_gate`
- `kicad://project/fix_queue`
- `kicad://schematic/connectivity`
- `kicad://board/placement_quality`

## Prompt Workflows

Built-in prompt helpers for the critic/fixer loop:

- `design_review_loop`
- `fix_blocking_issues`
- `manufacturing_release_checklist`

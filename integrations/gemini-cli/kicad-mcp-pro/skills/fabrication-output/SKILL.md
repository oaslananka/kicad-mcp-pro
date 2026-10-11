---
name: fabrication-output
description: KiCad MCP manufacturing release workflow for Gerbers, drill files, BOM, pick-and-place, DFM, release evidence, and final human review.
---

# Fabrication Output Skill

Use this skill when an AI agent is asked to prepare, validate, or package KiCad manufacturing outputs through KiCad MCP Pro.

This skill is specific to `oaslananka/kicad-mcp-pro` and should be kept synchronized with `docs/tools-reference.generated.md`.

## When to use

Use this skill for:

- Gerber and drill export
- BOM and pick-and-place export
- STEP/3D/PDF fabrication documentation
- DFM review
- Manufacturing quality gate review
- Release evidence and manifest generation
- Final manufacturing handoff preparation

Do not use this skill before ERC/DRC/DFM status is known.

## Required context

Collect:

- Active KiCad project path
- Target manufacturer or generic fabrication constraints
- Board stackup and layer count
- Assembly requirement: PCB only, SMT assembly, through-hole, mixed assembly, or prototype
- Required output directory
- Whether variants/DNP/population options apply
- Human approval status for unresolved violations and waivers

## Primary MCP tools

### Pre-release gates

- `kicad_get_project_info`
- `project_quality_gate`
- `project_quality_gate_report`
- `project_professional_release_gate`
- `project_release_readiness`
- `project_signoff_report`
- `run_erc`
- `run_drc`
- `check_design_for_manufacture`
- `manufacturing_quality_gate`

### Manufacturing and DFM tools

- `dfm_load_manufacturer_profile`
- `dfm_run_manufacturer_check`
- `dfm_calculate_manufacturing_cost`
- `mfg_generate_test_plan`
- `mfg_create_release_evidence`
- `mfg_generate_release_manifest`
- `mfg_correct_cpl_rotations`
- `pcb_check_creepage_clearance`
- `pcb_check_test_coverage`

### Export tools

- `export_manufacturing_package`
- `export_gerber`
- `export_drill`
- `export_bom`
- `export_pick_and_place`
- `export_netlist`
- `export_pcb_pdf`
- `export_sch_pdf`
- `export_step`
- `export_3d_render`
- `export_ipc2581`
- `export_odb`
- `export_ipc_d356`
- `jobset_list_templates`
- `jobset_validate`
- `jobset_export`
- `variant_export_manufacturing_package`

## Workflow

1. Confirm active project with `kicad_get_project_info`.
2. Run or retrieve project validation state using `project_quality_gate` or `project_quality_gate_report`.
3. Run `run_erc` and `run_drc` unless the user provides recent validated evidence.
4. Run DFM/manufacturing checks using `check_design_for_manufacture` and `manufacturing_quality_gate`.
5. If a manufacturer is specified, load and run the relevant DFM profile with `dfm_load_manufacturer_profile` and `dfm_run_manufacturer_check`.
6. Block release if there are unresolved critical ERC, DRC, DFM, stackup, or manufacturing-gate failures.
7. Export required artifacts with the smallest complete export set for the user's target.
8. Prefer `export_manufacturing_package` when a gated package is requested and supported.
9. Generate evidence and manifests with `mfg_create_release_evidence` and `mfg_generate_release_manifest` when available.
10. Report exact artifact types, output paths, gate results, known waivers, and human-review requirements.

## Minimum artifact set

For a typical PCB fabrication handoff:

- Gerber files from `export_gerber`
- Drill files from `export_drill`
- Board PDF or fabrication drawing from `export_pcb_pdf`
- Schematic PDF from `export_sch_pdf`
- BOM from `export_bom`
- Pick-and-place file from `export_pick_and_place` when assembly is required
- STEP model from `export_step` when mechanical review is required
- Release evidence/manifest when a formal release package is requested

## Quality checks

A manufacturing package response must include:

- ERC status
- DRC status
- DFM/manufacturing gate status
- Exported artifact list
- Output location
- Missing artifacts, if any
- Waivers and exclusions
- Human-review checklist

## Failure modes

Stop and report clearly when:

- ERC/DRC has unresolved critical failures
- DFM constraints are missing for a manufacturer-specific release
- Export tools fail or output paths are not writable
- BOM or pick-and-place data is incomplete
- Variants/DNP requirements are ambiguous
- The user asks to fabricate without validation evidence

## Output format

Return:

- Release target
- Gate status
- Artifact inventory
- Waivers/exclusions
- Blockers
- Human-review checklist
- Final verdict: `blocked`, `draft package`, or `candidate package after human review`

## Safety rule

Never represent generated fabrication files as production-approved. Use `candidate package after human review` unless a qualified human explicitly approves the release outside the agent workflow.

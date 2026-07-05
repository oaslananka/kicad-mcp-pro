---
name: drc-check
description: KiCad MCP workflow for ERC/DRC execution, issue triage, waiver review, and revalidation.
---

# DRC Check Skill

Use this skill when an AI agent is asked to run, interpret, triage, or revalidate KiCad ERC/DRC results through KiCad MCP Pro.

This skill is specific to `oaslananka/kicad-mcp` and should be kept synchronized with `docs/tools-reference.generated.md`.

## When to use

Use this skill for:

- Schematic ERC review
- PCB DRC review
- DRC rule inspection and custom rule checks
- Unconnected net triage
- Courtyard and silk-to-pad violation triage
- Waiver/exclusion review
- Revalidation after an edit

Do not use this skill to hide, auto-waive, or normalize violations without explicit engineering rationale.

## Required context

Collect:

- Active project path and KiCad version from `kicad_get_project_info`
- Board and schematic files
- Target gate: ERC, DRC, project gate, release gate, or revalidation loop
- Manufacturer or design-rule constraints, if relevant
- Existing waivers/exclusions, if any

## Primary MCP tools

### Setup and discovery

- `kicad_get_project_info`
- `kicad_get_version`
- `kicad_help`
- `kicad_get_tools_in_category`

### ERC and schematic checks

- `run_erc`
- `erc_list_rules`
- `schematic_quality_gate`
- `schematic_connectivity_gate`
- `schematic_design_rule_check`
- `sch_check_power_flags`
- `sch_get_net_names`
- `sch_get_symbols`

### DRC and board checks

- `run_drc`
- `drc_list_rules`
- `drc_check_rule_conflicts`
- `drc_list_exclusions`
- `drc_validate_exclusions`
- `get_unconnected_nets`
- `get_courtyard_violations`
- `get_silk_to_pad_violations`
- `pcb_quality_gate`
- `pcb_transfer_quality_gate`
- `pcb_stackup_consistency_gate`

### Controlled rule/exclusion operations

Use these only when explicitly requested and when the rationale is documented.

- `drc_add_exclusion`
- `drc_remove_exclusion`
- `drc_rule_create`
- `drc_rule_delete`
- `drc_rule_enable`
- `drc_export_rules`
- `erc_set_rule_severity`
- `erc_reset_rules`

### Project-level validation

- `project_quality_gate`
- `project_quality_gate_report`
- `project_full_validation_loop`
- `project_revalidate_after_edit`
- `project_gate_trend`

## Workflow

1. Confirm active project and KiCad capability with `kicad_get_project_info` and `kicad_get_version`.
2. Run ERC with `run_erc` when schematic validation is in scope.
3. Run DRC with `run_drc` when PCB validation is in scope.
4. Run targeted issue extractors: `get_unconnected_nets`, `get_courtyard_violations`, and `get_silk_to_pad_violations`.
5. Inspect rule configuration with `drc_list_rules`, `erc_list_rules`, and `drc_check_rule_conflicts` when violations are unclear.
6. Check exclusions with `drc_list_exclusions` and `drc_validate_exclusions`.
7. Run the relevant quality gates.
8. Group findings by severity, rule, object/reference, location, and likely fix.
9. If edits are performed by another workflow, re-run the targeted gates and compare before/after results.
10. Report remaining violations, accepted waivers, and unverified assumptions separately.

## Waiver policy

A DRC/ERC issue may be marked as waived only when the response documents:

- Rule name or violation ID
- Location/object/reference
- Expected requirement
- Actual deviation
- Engineering rationale
- Human approval requirement

Do not add DRC exclusions automatically just to make a gate pass.

## Quality checks

A complete DRC/ERC report must include:

- Tool versions or project context
- ERC result summary
- DRC result summary
- Issue counts by severity
- Critical blockers
- Waivers/exclusions status
- Recommended fixes
- Revalidation result after any changes

## Failure modes

Stop and report clearly when:

- KiCad CLI is unavailable for file-backed checks
- Project paths are ambiguous
- DRC/ERC output cannot be produced
- Rule files are missing or conflicting
- Exclusions are stale or cannot be validated
- The user asks to suppress violations without an engineering reason

## Output format

Return:

- Project context
- ERC summary
- DRC summary
- Rule/exclusion status
- Findings by severity
- Recommended fixes
- Revalidation evidence
- Human-review notes

---
name: kicad-design-review
description: Comprehensive KiCad design review skill covering schematic, PCB, DFM, manufacturing, high-speed, and simulation review workflows.
---

# KiCad Design Review Skill

Use this skill for any KiCad project review task: schematic correctness, PCB layout quality, DFM readiness, manufacturing release, and simulation verification.

## When to Use

- Board review before manufacturing
- Schematic review before PCB layout
- DFM check before fab submission
- Manufacturing release preparation
- High-speed design review
- SPICE simulation review

## Required Tools

### Phase 1 — Project Inspection
1. `kicad_get_project_info` — project metadata and KiCad version
2. `project_quality_gate` — comprehensive quality report
3. `pcb_get_board_summary` — board dimensions, layers, component count
4. `sch_get_symbols` — component list

### Phase 2 — Electrical Validation
1. `run_erc` — all electrical rules
2. `sch_get_net_names` — verify net connectivity

### Phase 3 — Physical Validation
1. `run_drc` — all design rules
2. `pcb_get_nets` — net and track statistics

### Phase 4 — DFM / Manufacturing
1. `check_design_for_manufacture` — DFM rules
2. `manufacturing_quality_gate` — manufacturing readiness
3. `export_gerber` / `export_drill` / `export_bom` — release artifacts

### Phase 5 — Final Report
- List all warnings and errors by severity
- Provide a manufacturing readiness verdict
- Document any waived issues

## Quality Gates

| Gate | What It Checks |
|------|---------------|
| `project_quality_gate` | Overall project health |
| `schematic_quality_gate` | Schematic correctness |
| `schematic_connectivity_gate` | Net connectivity |
| `pcb_quality_gate` | PCB layout quality |
| `pcb_placement_quality_gate` | Component placement |
| `pcb_transfer_quality_gate` | Schematic-to-PCB sync |
| `manufacturing_quality_gate` | Manufacturing readiness |

## Refusal Policy

Do not approve a design for manufacturing unless:
- All quality gates pass or issues are explicitly documented
- ERC and DRC show zero errors
- DFM checks are complete
- Export artifacts are verified

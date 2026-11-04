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

## Review Lifecycle Stages

1. **`PLAN_COMPLETION`** — Verifies design intent, interfaces, and architecture contracts before routing.
2. **`DESIGN_REVIEW`** — Full schematic ERC, PCB DRC, supply net connectivity, connector mating, component derating, and DFM profile compliance.
3. **`PROTOTYPE_TEST`** — Numerical simulation evidence, test point accessibility, and hardware bring-up plan with acceptance limits.
4. **`PRODUCTION_ACCEPTANCE`** — Final signoff, human CAM approval, verified BOM stock, and independent power-on authorization.

## Evidence Hierarchy & Invariants

- **Native KiCad execution** (`run_erc`, `run_drc`) provides ground-truth electrical and spacing status.
- **Analytical reviews** verify derating, decoupling topology, thermal dissipation, and geometry.
- **External simulation reports** require matching design SHA256, stackup identity, and solver convergence.
- **Bring-up measurements** must record instrument ID, environmental temperature, and measured values against min/max bounds. A completed checklist without measurements is not measurement evidence.
- **Missing inputs or unassessed rules** evaluate to `NOT_ASSESSED` or `BLOCKED`, never silent `PASS`.

## Hard Stop Conditions

Do not approve a design for manufacturing or stage progression if any of these hold:
- **Mechanical connector failure:** Connector mating direction points away from board edge or lacks datum alignment (#1393). Electrical PASS never overrides mechanical FAIL.
- **False-coupling placement:** Decoupling capacitor placed physically adjacent to an IC but connected to wrong power/ground nets is a critical defect (#1582).
- **Fabricator process limit violation:** PTH annular ring below selected fabricator floor (e.g. USB4085 0.125 mm vs JLCPCB 2-layer 0.18 mm, #1381) requires a documented fabricator exception; generic DFM scores cannot waive it.
- **Hazardous mains safety:** High-voltage circuits require explicit specialist insulation coordination and creepage review; keyword presence in .dru rules does not suffice (#1584).
- **Separated authorizations:** Production release cannot be authorized without completed and authorized hardware power-on bring-up (#1586).
- **Advisory separation:** Aesthetic routing style (90-degree corners) and cosmetic readability must be reported as advisory recommendations, not blocking engineering failures (#1581).

## Refusal Policy

Do not approve a design for manufacturing unless:
- All quality gates pass or issues are explicitly documented and waived by a qualified engineer
- ERC and DRC show zero errors
- Selected fabricator/assembler capability profile is loaded and verified
- DFM/DFA checks are complete with all required inputs present
- Export artifacts are verified

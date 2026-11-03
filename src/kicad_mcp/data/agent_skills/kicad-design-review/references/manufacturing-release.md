# Manufacturing Release Workflow

## Pre-Release Gate
```
project_quality_gate → run_erc → run_drc → check_design_for_manufacture
```

## Export Order
1. `export_gerber` — all signal, power, and mask layers
2. `export_drill` — NC drill files (all drill sizes)
3. `export_bom` — bill of materials with MPNs
4. `export_pick_and_place` — centroid file for assembly
5. `export_3d_step` — 3D model
6. `export_pcb_pdf` — fabrication drawing
7. `export_sch_pdf` — schematic PDF

## Post-Export Verification
- Verify Gerber files with a Gerber viewer
- Cross-check BOM against schematic
- Review pick-and-place coordinates
- Generate release manifest
- Compress into manufacturing package

## Waiver Documentation
Any DRC/DFM waiver must be documented with:
- Rule name and expected value
- Actual value and deviation
- Reason for waiver
- Engineering approval

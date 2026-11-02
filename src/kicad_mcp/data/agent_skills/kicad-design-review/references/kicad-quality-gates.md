# KiCad MCP Quality Gates

| Quality Gate | Tools Used | Scope |
|-------------|-----------|-------|
| `project_quality_gate` | Multiple | Overall project health, file integrity, version compatibility |
| `schematic_quality_gate` | `run_erc`, `sch_get_symbols` | Schematic correctness, ERC pass |
| `schematic_connectivity_gate` | `sch_get_net_names` | Net connectivity, missing connections |
| `pcb_quality_gate` | `run_drc`, `pcb_get_board_summary` | PCB layout, DRC pass, design rules |
| `pcb_placement_quality_gate` | `pcb_get_board_summary` | Component placement density, clearance |
| `pcb_transfer_quality_gate` | Schematic vs PCB sync check | Schematic-to-PCB annotation sync |
| `manufacturing_quality_gate` | `check_design_for_manufacture` | DFM rules, fab capability, stackup |
| `project_quality_gate_report` | All gates | Comprehensive human-readable report |
| `project_full_validation_loop` | All gates + exports | Full pre-release validation |
| `project_auto_fix_loop` | All gates + write | Automated fix attempt loop |

# KiCad MCP Tool Map

## Read-only Tools
| Tool | Description |
|------|-------------|
| `kicad_get_project_info` | Project metadata, KiCad version, file paths |
| `pcb_get_board_summary` | Board layer count, dimensions, component count |
| `pcb_get_nets` | Net list with track/via statistics |
| `pcb_get_tracks` | Existing PCB tracks, including object identifiers used for targeted edits |
| `pcb_get_vias` | Existing PCB vias, including object identifiers used for targeted edits |
| `sch_get_symbols` | Schematic symbol list with references |
| `sch_get_net_names` | Net names from schematic |
| `run_erc` | Electrical rules check |
| `run_drc` | Design rules check |
| `validate_design` | Combined validation |
| `project_quality_gate` | Full quality gate suite |

## Write Tools
| Tool | Description |
|------|-------------|
| `pcb_add_track` | Add track segment |
| `pcb_add_via` | Add via |
| `pcb_delete_items` | Remove one or more PCB objects by UUID through KiCad IPC |
| `pcb_delete_object` | Remove one PCB object by UUID through KiCad IPC |
| `sch_add_component` | Add component to schematic |
| `route_autoroute_freerouting` | Auto-route with FreeRouting |

## Export Tools
| Tool | Description |
|------|-------------|
| `export_gerber` | Gerber files |
| `export_drill` | NC drill files |
| `export_bom` | Bill of Materials |
| `export_pick_and_place` | Pick and place file |
| `export_3d_step` | 3D STEP model |
| `export_manufacturing_package` | Complete manufacturing package |

## DFM/Quality Tools
| Tool | Description |
|------|-------------|
| `check_design_for_manufacture` | DFM rule checks |
| `manufacturing_quality_gate` | Manufacturing readiness gate |
| `pcb_quality_gate` | PCB-specific quality checks |

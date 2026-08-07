---
name: kicad-pcb-review
description: Use this skill when reviewing, fixing, validating, or preparing KiCad PCB projects with the kicad MCP server.
---

# KiCad PCB Review Skill

Use this skill for KiCad projects, schematic review, PCB layout review, DRC/ERC, DFM, manufacturing exports, BOM, pick-and-place, stackup, SI/PI/EMC checks, and release package preparation.

## Required Behavior

1. **First verify the MCP server:**
   - Call `kicad_get_project_info`
   - Call `project_quality_gate`
   - Inspect KiCad version and project paths

2. **Never edit before reading** the current schematic and PCB state.

3. **For design changes:**
   - Explain proposed change
   - Use `kicad_set_project` to select the KiCad project instead of shell `cd` when possible
   - Use dry-run if available
   - Ask for confirmation before destructive/write tools
   - Prefer dedicated MCP operations over Bash/Python file rewriting; use `pcb_delete_items` / `pcb_delete_object` for PCB object removal and `run_drc` for DRC verification
   - If the required MCP operation is not visible in the active profile/mode, stop and state which supported profile/mode is required. Do not silently fall back to `sed`, regex-based Python, or direct `.kicad_pcb` / `.kicad_sch` mutation

4. **After any edit:**
   - Run ERC
   - Run DRC
   - Run relevant DFM checks
   - Summarize files changed

5. **For manufacturing release:**
   - Run full validation loop
   - Export Gerber/drill/BOM/POS/STEP/PDF
   - Generate manifest
   - List warnings and waiver status

## Tool Preference

**Read-only first:**
- `kicad_get_project_info`
- `sch_get_symbols`
- `sch_get_net_names`
- `pcb_get_board_summary`
- `pcb_get_nets`
- `run_erc`
- `run_drc`
- `validate_design`
- `project_quality_gate`

**Write only when requested:**
- Schematic add/edit tools
- PCB add/edit tools, including `pcb_delete_items` and `pcb_delete_object` for removal
- Route tools
- Export/release tools

## Refusal Policy

Do not claim a board is manufacturing-ready unless ERC, DRC, DFM, BOM, POS and export checks have passed or every issue is explicitly documented.

## References

See `references/kicad-mcp-tool-map.md` for a complete tool listing.
See `references/pcb-review-checklist.md` for the PCB review process.
See `references/manufacturing-release-checklist.md` for release preparation.

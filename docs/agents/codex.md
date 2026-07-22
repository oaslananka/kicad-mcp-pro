# Codex CLI Integration

## Quick Start

```bash
kicad-mcp-pro setup codex
```

Or manually add to `~/.codex/config.toml`:

```toml
[mcp_servers.kicad]
enabled = true
command = "uvx"
args = ["kicad-mcp-pro"]
cwd = "."
default_tools_approval_mode = "never"
enabled_tools = [
    "kicad_get_project_info",
    "pcb_get_board_summary",
    "sch_get_symbols",
    "run_drc",
    "run_erc",
    "validate_design",
    "project_quality_gate"
]

[mcp_servers.kicad.env]
KICAD_MCP_PROJECT_DIR = "."
KICAD_MCP_PROFILE = "default"
KICAD_MCP_OPERATING_MODE = "readonly"
```

## Verification

Run: `kicad-mcp-pro doctor --agent codex`

The kicad tools appear automatically in Codex CLI when the config is present.

## Smoke Test Prompt

> Use the kicad MCP server. Inspect this KiCad project, identify the board, schematic, KiCad version, run the available quality gates, and summarize whether the project is ready for PCB review. Do not modify files.

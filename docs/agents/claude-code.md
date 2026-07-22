# Claude Code Integration

## Quick Start

```bash
claude mcp add --transport stdio --scope project kicad -- uvx kicad-mcp-pro
```

Or with project scope `.mcp.json`:

```json
{
  "mcpServers": {
    "kicad": {
      "type": "stdio",
      "command": "uvx",
      "args": ["kicad-mcp-pro"],
      "env": {
        "KICAD_MCP_PROJECT_DIR": "${CLAUDE_PROJECT_DIR:-.}",
        "KICAD_MCP_PROFILE": "default",
        "KICAD_MCP_OPERATING_MODE": "readonly"
      }
    }
  }
}
```

## Skill Installation

```bash
cp -r integrations/claude-code/kicad-pcb-review-skill ~/.claude/skills/
```

The skill auto-loads for KiCad PCB review tasks.

## Verification

```
/mcp  →  list connected servers
```

## Example Prompts

### Read-only inspection
> Use the kicad MCP server. Inspect this KiCad project, identify the board, schematic, KiCad version, run the available quality gates, and summarize whether the project is ready for PCB review. Do not modify files.

### ERC/DRC
> Use kicad MCP read-only tools to run ERC and DRC. Group issues by severity, explain likely causes, and propose a safe fix plan. Do not edit until I approve.

### Manufacturing
> Use kicad MCP to check whether this board is manufacturing-ready for JLCPCB/PCBWay. Run quality gates, inspect BOM/POS/export readiness, and produce a release checklist. Do not generate files yet.

### Write (guarded)
> Use kicad MCP to fix the approved issue only. Before any write operation, show the exact tool and intended change. After editing, run ERC/DRC and summarize changed files.

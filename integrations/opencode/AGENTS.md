# KiCad MCP — OpenCode Usage Guide

When a task involves KiCad, PCB design, schematic review, ERC/DRC, manufacturing
export, BOM, routing, DFM, or KiCad project files, use the configured `kicad` MCP
server.

## Default policy

1. Inspect the current project state before proposing or making edits.
2. Prefer read-only MCP operations unless the user explicitly requests a change.
3. Run `project_quality_gate` before describing a design as release-ready.
4. Never execute destructive or irreversible tools without explicit user intent.
5. After edits, run the applicable ERC/DRC and validation gates and report the
   changed files and remaining violations.

## OpenCode permissions

OpenCode permission keys match tool names and support wildcards. For example,
`"kicad_*": "ask"` gates every tool exposed by the `kicad` MCP server. Per-agent
permission rules override the global policy, so a dedicated review agent can allow
KiCad reads while keeping `edit` denied and `bash` gated.

The legacy `tools` boolean configuration is deprecated; use `permission` for new
configurations.

## Quick start

```bash
uvx kicad-mcp-pro
```

Once `opencode.json` contains the MCP entry, OpenCode discovers the KiCad tools
from the server automatically.

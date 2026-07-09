# Cursor — KiCad MCP Integration

Connect [Cursor](https://cursor.sh) to KiCad via the `kicad-mcp-pro` MCP server with MCP config, Rules, and Skills.

## Quick Install

```bash
kicad-mcp-pro setup cursor
```

Or manually:

1. Copy `mcp.example.json` to `.cursor/mcp.json` in your project.
2. Copy `rules/kicad.mdc` to `.cursor/rules/kicad.mdc`.
3. (Optional) Copy `skills/kicad-pcb-review/SKILL.md` to `.cursor/skills/kicad-pcb-review/`.
4. Restart Cursor.

## What's Included

| Folder | Purpose |
|--------|---------|
| `mcp.example.json` | MCP server STDIO config |
| `rules/kicad.mdc` | Cursor Rule that instructs the agent when to use kicad MCP |
| `skills/kicad-pcb-review/` | Agent Skill for PCB review workflows |

## Verification

```bash
kicad-mcp-pro doctor --agent cursor
```

In Cursor Agent mode, ask: *"Use kicad MCP to inspect this project."*

## Security

- Start with read-only mode.
- MCP tools require confirmation in Agent mode.

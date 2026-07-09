# Codex CLI — KiCad MCP Integration

Connect [Codex CLI](https://github.com/openai/codex) to your local KiCad projects via the `kicad-mcp-pro` MCP server.

## Quick Install

```bash
kicad-mcp-pro setup codex
```

Or manually:

1. Copy `config.toml.example` to `~/.codex/config.toml`.
2. Edit `KICAD_MCP_PROJECT_DIR` to match your KiCad project root.
3. Start Codex CLI — the `kicad` MCP server appears automatically.

## Profiles

| Mode | Config | Behavior |
|------|--------|----------|
| **Read-only** (default) | `enabled_tools = [...]` | Inspect project, run ERC/DRC, validate |
| **Write** | Change `default_tools_approval_mode` to `"prompt"` | Edit schematic/PCB, export, route |

## AGENTS.md

Add this to your Codex `AGENTS.md` for best results:

```markdown
When the task involves KiCad, use the `kicad` MCP server first.
Default policy: inspect before editing. Run `project_quality_gate` before release.
Never run destructive tools without explicit user confirmation.
```

## Verification

```bash
kicad-mcp-pro doctor --agent codex
```

## Security

- Start with `readonly` mode.
- Do not enable write tools for untrusted projects.
- Review all tool calls before approving destructive operations.

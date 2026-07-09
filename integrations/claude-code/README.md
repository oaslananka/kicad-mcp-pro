# Claude Code — KiCad MCP Integration

Connect [Claude Code](https://docs.anthropic.com/en/docs/claude-code) to KiCad via the `kicad-mcp-pro` MCP server.

## Quick Install (One Command)

```bash
kicad-mcp-pro setup claude-code
```

Or manually:

```bash
claude mcp add --transport stdio --scope project kicad -- uvx kicad-mcp-pro
```

## Remote Cloud

```bash
claude mcp add --transport http --scope user kicad-cloud https://mcp.kicad.example.com/mcp
```

## Project Config

Copy `.mcp.json.example` to `.mcp.json` in your project root. Claude Code detects it automatically.

## Skill Paketi

The `kicad-pcb-review-skill/` directory contains a Claude Code Skill for PCB review workflows:

```bash
# Install the skill
cp -r kicad-pcb-review-skill ~/.claude/skills/
```

The skill auto-loads when KiCad projects are detected. See `kicad-pcb-review-skill/SKILL.md` for the full workflow.

## Verification

```bash
kicad-mcp-pro doctor --agent claude-code
```

In Claude Code: `/mcp` to verify the kicad server is connected.

## Security

- Project-scope servers require user approval in Claude Code.
- Start with read-only mode.
- Remote connectors cannot access local KiCad directly.

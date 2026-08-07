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

The generated configuration starts in bounded read-only mode. For a trusted project where PCB/schematic edits are intended, generate the supported write-mode configuration explicitly:

```bash
kicad-mcp-pro setup claude-code --mode write --write --scope project
```

Write mode uses the bounded `build` profile. It includes transaction controls plus targeted PCB inspection/removal and DRC verification so an agent does not need to rewrite KiCad files with ad-hoc shell or Python commands. If a required MCP tool is outside the active profile, switch profiles/modes explicitly rather than using raw `.kicad_pcb` / `.kicad_sch` text mutation as a fallback.

Claude Code can still ask for approval when the agent actually invokes Bash or another local command; those shell permission prompts are enforced by Claude Code itself and are separate from KiCad MCP Pro's MCP tool surface.

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

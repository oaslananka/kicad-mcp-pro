# Claude Code — KiCad MCP Integration

Connect [Claude Code](https://docs.anthropic.com/en/docs/claude-code) to KiCad via the `kicad-mcp-pro` MCP server.

## Quick Install (One Command)

```bash
uvx kicad-mcp-pro quickstart --agent claude-code
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

Merge only `mcpServers.kicad` from `.mcp.json.example` into your project `.mcp.json`.
Preserve other servers and approve the new entry in Claude Code when prompted.

## Skills and plugin

Quickstart installs the seven bundled KiCad skills into the chosen scope and
preserves conflicting or edited workflows. Use `--no-skills` if your native
plugin already supplies them. To manage just the skills, use
`kicad-mcp-pro skills status --agent claude-code` with the same project directory
and scope. Replace `status` with `install` or `remove` for those actions.

For a trusted source checkout, `claude plugin validate .` and
`claude --plugin-dir .` validate/load the product plugin with its bundled MCP
configuration and canonical skills. Verify actual host discovery after loading.
See the [installation guide](../../docs/agents/install.md) for prerequisites and
the distinction between saved configuration and a real agent tool call.

## Verification

```bash
kicad-mcp-pro doctor
```

In Claude Code: `/mcp` to verify the kicad server is connected.

## Security

- Project-scope servers require user approval in Claude Code.
- Start with read-only mode.
- Remote connectors cannot access local KiCad directly.

# Claude Desktop — KiCad MCP Integration

Connect [Claude Desktop](https://claude.ai/desktop) to your local KiCad projects via the `kicad-mcp-pro` MCP server.

## Quick Install

```bash
kicad-mcp-pro setup claude-desktop
```

Or manually:

### macOS
Config path: `~/Library/Application Support/Claude/claude_desktop_config.json`

### Windows
Config path: `%APPDATA%\Claude\claude_desktop_config.json`

### Linux
Config path: `~/.config/Claude/claude_desktop_config.json`

1. Copy `claude_desktop_config.example.json` to the appropriate path.
2. Replace `KICAD_MCP_PROJECT_DIR` with the absolute path to your KiCad project.
3. Restart Claude Desktop.

## Verification

```bash
kicad-mcp-pro doctor --agent claude-desktop
```

In Claude Desktop, ask: *"Use the kicad MCP server to inspect the current project."*

## Security

- Start with read-only mode.
- Claude Desktop local config runs on your machine; write tools require explicit approval.

> **Note**: Claude Desktop local config is separate from Claude.ai custom connectors. Local config controls a local MCP server; Claude.ai connectors require a public remote endpoint.

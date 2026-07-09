# Google Antigravity — KiCad MCP Integration

Connect [Antigravity IDE](https://github.com/google/antigravity) to KiCad via the `kicad-mcp-pro` MCP server.

## Quick Install

```bash
kicad-mcp-pro setup antigravity
```

Or manually:

1. Copy `mcp_config.example.json` to `~/.gemini/config/mcp_config.json`.
2. Edit `KICAD_MCP_PROJECT_DIR` to match your KiCad project.
3. In Antigravity IDE: **MCP Servers → Manage MCP Servers**.
4. Verify with `/mcp` in the CLI.

## Configuration

Antigravity uses a shared config file with Gemini CLI. Both IDE and CLI read from `~/.gemini/config/mcp_config.json`.

## Security

- First tool use triggers a confirmation prompt.
- Start with read-only mode.
- Remote servers require `serverUrl` and optional `Authorization` header.

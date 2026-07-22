# Google Antigravity Integration

## Quick Start

```bash
kicad-mcp-pro setup antigravity
```

Or manually add to `~/.gemini/config/mcp_config.json`:

```json
{
  "mcpServers": {
    "kicad": {
      "command": "uvx",
      "args": ["kicad-mcp-pro"],
      "env": {
        "KICAD_MCP_PROJECT_DIR": ".",
        "KICAD_MCP_PROFILE": "default",
        "KICAD_MCP_OPERATING_MODE": "readonly"
      }
    }
  }
}
```

## IDE Setup

1. Open Antigravity IDE
2. Go to **MCP Servers → Manage MCP Servers**
3. Click **View raw config** to edit the JSON
4. Paste the kicad config
5. Verify with `/mcp` in the CLI

## Verification

```
/mcp  →  verify kicad server is connected
```

## Security

- First tool use triggers a confirmation prompt
- Start with read-only mode
- Remote servers use `serverUrl` with optional `Authorization` header

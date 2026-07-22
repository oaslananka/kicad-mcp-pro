# OpenCode — KiCad MCP Integration

Connect [OpenCode](https://opencode.ai) to KiCad via the `kicad-mcp-pro` MCP server.

## Quick Install

```bash
kicad-mcp-pro setup opencode
```

Or manually, add to your `opencode.json`:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "kicad": {
      "type": "local",
      "command": ["uvx", "kicad-mcp-pro"],
      "enabled": true,
      "environment": {
        "KICAD_MCP_PROJECT_DIR": ".",
        "KICAD_MCP_PROFILE": "default",
        "KICAD_MCP_OPERATING_MODE": "readonly"
      }
    }
  }
}
```

## Remote

```json
{
  "mcp": {
    "kicad-cloud": {
      "type": "remote",
      "url": "https://mcp.kicad.example.com/mcp",
      "enabled": true,
      "headers": {
        "Authorization": "Bearer {env:KICAD_MCP_TOKEN}"
      }
    }
  }
}
```

## Plugin

An experimental OpenCode plugin is available at `plugins/kicad-mcp-plugin/`. It provides:
- Config wizard
- `kicad:doctor` command
- `kicad:review` command
- Toolset switcher

## Verification

```bash
kicad-mcp-pro doctor --agent opencode
opencode mcp list
```

## Security

- Start with read-only mode.
- Use glob patterns (`kicad_*`) in `tools` section to control per-agent tool access.
- Remote servers support OAuth auto-detection and secure token storage.

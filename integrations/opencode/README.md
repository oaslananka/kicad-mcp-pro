# OpenCode — KiCad MCP Integration

Connect [OpenCode](https://opencode.ai) to KiCad through the `kicad-mcp-pro`
MCP server.

## Quick install

```bash
kicad-mcp-pro setup opencode
```

Or add a local server to `opencode.json`:

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

OpenCode permissions support wildcard matching against tool names, including MCP
tools. A conservative default is to deny the KiCad tool family globally and allow
it only for a dedicated agent:

```json
{
  "permission": {
    "kicad_*": "deny",
    "edit": "ask",
    "bash": "ask"
  },
  "agent": {
    "pcb-review": {
      "description": "KiCad PCB review and manufacturing readiness agent",
      "mode": "primary",
      "permission": {
        "kicad_*": "allow",
        "edit": "deny",
        "bash": "ask"
      }
    }
  }
}
```

See `opencode.example.json` for the complete example.

## Remote server

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

## Verification

```bash
kicad-mcp-pro doctor --agent opencode
opencode mcp list
```

## Experimental plugin

The experimental plugin under `plugins/kicad-mcp-plugin/` provides a configuration
wizard plus `kicad:doctor`, `kicad:review`, and manufacturing-readiness commands.
Treat it as optional; the MCP server does not require the plugin.

## Security

Start with `KICAD_MCP_OPERATING_MODE=readonly`. Use OpenCode `permission` rules,
not the deprecated legacy `tools` booleans, to constrain built-in and MCP tools.
Keep write-capable agents narrow, require human intent before destructive KiCad
operations, and use environment-variable references rather than literal remote
tokens in configuration.

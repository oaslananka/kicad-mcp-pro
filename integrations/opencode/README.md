# OpenCode — KiCad MCP Integration

Connect [OpenCode](https://opencode.ai) to KiCad through the `kicad-mcp-pro`
MCP server.

## Quick install

```bash
kicad-mcp-pro setup opencode
```

For OpenCode 2.x, add this local server to `opencode.json`:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "servers": {
      "kicad": {
        "type": "local",
        "command": ["uvx", "kicad-mcp-pro", "--transport", "stdio"],
        "codemode": false,
        "environment": {
          "KICAD_MCP_PROJECT_DIR": ".",
          "KICAD_MCP_PROFILE": "default",
          "KICAD_MCP_OPERATING_MODE": "readonly"
        }
      }
    }
  }
}
```

`setup opencode` detects the installed OpenCode major version (defaulting to 2.x
when absent). OpenCode 1.x uses the preserved `opencode.v1.example.json` schema.

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

See `opencode.example.json` for the 2.x example and
`opencode.v1.example.json` for the older 1.x format.

## Remote server

```json
{
  "mcp": {
    "servers": {
      "kicad-cloud": {
        "type": "remote",
        "url": "https://mcp.kicad.example.com/mcp",
        "headers": {
          "Authorization": "Bearer {env:KICAD_MCP_TOKEN}"
        }
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

# OpenCode — KiCad MCP Integration

Connect [OpenCode](https://opencode.ai) to KiCad through the `kicad-mcp-pro`
MCP server.

## Quick install

```bash
uvx kicad-mcp-pro quickstart --agent opencode
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

`setup opencode` generates the current 2.x schema by default. To generate the
legacy 1.x format instead, set `KICAD_MCP_OPENCODE_CONFIG_VERSION=1` for that
setup command (or copy `opencode.v1.example.json`). No OpenCode CLI process is
executed just to inspect a version.

OpenCode 2.x uses ordered `permissions` arrays and `agents` entries (not
the legacy 1.x `permission` and `agent` maps). Its tool names are prefixed by
the MCP server name, so `kicad_*` covers this configuration's KiCad tools.
A conservative default is to deny the KiCad tool family globally and allow
it only for a dedicated agent:

```json
{
  "permissions": [
    {"action": "kicad_*", "resource": "*", "effect": "deny"},
    {"action": "edit", "resource": "*", "effect": "ask"},
    {"action": "shell", "resource": "*", "effect": "ask"}
  ],
  "agents": {
    "pcb-review": {
      "description": "KiCad PCB review and manufacturing readiness agent",
      "mode": "primary",
      "permissions": [
        {"action": "kicad_*", "resource": "*", "effect": "allow"},
        {"action": "edit", "resource": "*", "effect": "deny"},
        {"action": "shell", "resource": "*", "effect": "ask"}
      ]
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
kicad-mcp-pro doctor
opencode mcp list
# If the KiCad server is missing, reload and check again:
opencode reload
opencode mcp list
```

For OpenCode 2.x, run `opencode reload` from the configured project only
if the KiCad MCP server is missing after a config change. The background service can
otherwise retain an old connection list even while the config file is
correct. Confirm the KiCad server is connected. Reload rebuilds active
locations and may cancel pending permissions or forms; do it only when the
host is idle. Do not use experimental runtime-registration endpoints as an
installation workaround.

## Experimental plugin

The experimental plugin under `plugins/kicad-mcp-plugin/` provides a configuration
wizard plus `kicad:doctor`, `kicad:review`, and manufacturing-readiness commands.
Treat it as optional; the MCP server does not require the plugin.

## Security

Start with `KICAD_MCP_OPERATING_MODE=readonly`. Use OpenCode 2.x ordered `permissions` rules (1.x used `permission`),
not deprecated legacy `tools` booleans, to constrain built-in and MCP tools.
Keep write-capable agents narrow, require human intent before destructive KiCad
operations, and use environment-variable references rather than literal remote
tokens in configuration.

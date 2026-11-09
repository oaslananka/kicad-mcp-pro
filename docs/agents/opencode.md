# OpenCode Integration

KiCad MCP Pro supports OpenCode as both an MCP client integration and a
maintainer-triggered pull-request repair agent.

## MCP quick start

```bash
uvx kicad-mcp-pro quickstart --agent opencode
```

On OpenCode 2.x, use the following minimal manual configuration (OpenCode
1.x uses `integrations/opencode/opencode.v1.example.json`, or set
`KICAD_MCP_OPENCODE_CONFIG_VERSION=1` when running `setup opencode`):

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

OpenCode permissions match tool names and support wildcards. Prefer the current
`permission` schema over the deprecated legacy `tools` booleans:

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

## Verification

```bash
opencode mcp list
# If the KiCad server is missing, reload and check again:
opencode reload
opencode mcp list
kicad-mcp-pro doctor
```

If the KiCad server is not listed after writing `opencode.json`,
`opencode reload` refreshes the existing service's configuration without a
restart. Verify that the KiCad server reports connected before using its
tools. Reloading active locations can cancel pending permission dialogs or
forms, so run it when no approval is in progress. The experimental MCP
registration API is not needed.

## Experimental plugin

An experimental OpenCode plugin is available at
`integrations/opencode/plugins/kicad-mcp-plugin/`. It provides diagnostics and
KiCad review helpers, but it is not required by the MCP configuration.

# OpenCode Integration

## Quick Start

```bash
kicad-mcp-pro setup opencode
```

Or manually add to `opencode.json`:

```json
{
  "mcp": {
    "kicad": {
      "type": "local",
      "command": ["uvx", "kicad-mcp-pro"],
      "enabled": true,
      "timeout": 30000,
      "environment": {
        "KICAD_MCP_PROJECT_DIR": ".",
        "KICAD_MCP_PROFILE": "default",
        "KICAD_MCP_OPERATING_MODE": "readonly"
      }
    }
  }
}
```

## Agent Configuration

```json
{
  "agent": {
    "pcb-review": {
      "description": "KiCad PCB review and manufacturing readiness agent",
      "tools": { "kicad_*": true, "write": false, "bash": "ask" }
    }
  }
}
```

## Verification

```bash
opencode mcp list
kicad-mcp-pro doctor --agent opencode
```

## Plugin

An experimental plugin is available at `integrations/opencode/plugins/kicad-mcp-plugin/` providing:
- `kicad:doctor` — run diagnostics
- `kicad:review` — PCB review workflow
- `kicad:manufacturing-check` — manufacturing readiness

Install with:
```json
{
  "plugins": ["@kicad-mcp/opencode-plugin"]
}
```

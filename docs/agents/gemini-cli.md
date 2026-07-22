# Gemini CLI Integration

## Quick Start

```bash
kicad-mcp-pro setup gemini
```

Or manually add to `~/.gemini/settings.json`:

```json
{
  "mcpServers": {
    "kicad": {
      "command": "uvx",
      "args": ["kicad-mcp-pro"],
      "env": {
        "KICAD_MCP_PROJECT_DIR": "$PWD",
        "KICAD_MCP_PROFILE": "default",
        "KICAD_MCP_OPERATING_MODE": "readonly"
      },
      "cwd": ".",
      "timeout": 30000,
      "trust": false,
      "includeTools": [
        "kicad_get_project_info",
        "project_quality_gate",
        "run_erc",
        "run_drc",
        "validate_design"
      ]
    }
  }
}
```

## Verification

```
/mcp  →  verify the kicad server is connected
```

## Slash Prompt

Add to your Gemini repo instructions:

> When the task involves KiCad, use the kicad MCP server.
> Default policy: inspect before editing. Run quality gates before suggesting release.
> Never run destructive tools without explicit user confirmation.
> Prefer read-only tools first.

## Remote

```json
{
  "mcpServers": {
    "kicad-cloud": {
      "httpUrl": "https://mcp.kicad.example.com/mcp",
      "timeout": 30000,
      "trust": false,
      "includeTools": ["search_kicad_knowledge", "analyze_uploaded_kicad_project"]
    }
  }
}
```

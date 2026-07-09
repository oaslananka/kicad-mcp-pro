# Gemini CLI — KiCad MCP Integration

Connect [Gemini CLI](https://cloud.google.com/gemini-cli) to your local KiCad projects via the `kicad-mcp-pro` MCP server.

## Quick Install

```bash
kicad-mcp-pro setup gemini
```

Or manually:

1. Copy `settings.example.json` to `~/.gemini/settings.json`.
2. Ensure `KICAD_MCP_PROJECT_DIR` points to your project.
3. Start Gemini CLI and run `/mcp` to verify the `kicad` server is connected.
4. Try: `Use the kicad MCP server to inspect this project.`

## Profiles

| Mode | Config | Behavior |
|------|--------|----------|
| **Read-only** (default) | `"includeTools": [...]` | Inspect, validate, run DRC/ERC |
| **Write** | Remove `includeTools` | Full tool access with confirmation |

## Local vs Remote

```json
{
  "mcpServers": {
    "kicad-cloud": {
      "httpUrl": "https://mcp.kicad.example.com/mcp",
      "timeout": 30000,
      "trust": false,
      "includeTools": ["search_kicad_knowledge", "generate_manufacturing_readiness_report"]
    }
  }
}
```

## Verification

```bash
kicad-mcp-pro doctor --agent gemini
```

## Security

- Default `"trust": false` requires confirmation on first tool use.
- OAuth remote MCP supports browser auth flow; headless/SSH environments have limitations documented in troubleshooting.

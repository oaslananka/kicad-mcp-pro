# Claude Desktop Integration

## Quick Start

```bash
kicad-mcp-pro setup claude-desktop
```

Or manually:

### macOS
`~/Library/Application Support/Claude/claude_desktop_config.json`

### Windows
`%APPDATA%\Claude\claude_desktop_config.json`

### Linux
`~/.config/Claude/claude_desktop_config.json`

```json
{
  "mcpServers": {
    "kicad": {
      "command": "uvx",
      "args": ["kicad-mcp-pro"],
      "env": {
        "KICAD_MCP_PROJECT_DIR": "/absolute/path/to/kicad/project",
        "KICAD_MCP_PROFILE": "analysis",
        "KICAD_MCP_OPERATING_MODE": "readonly"
      }
    }
  }
}
```

## Important

Claude Desktop local config is **separate** from Claude.ai custom connectors. Local config runs directly on your machine with full KiCad access. Claude.ai connectors require a public remote endpoint.

## Verification

```bash
kicad-mcp-pro doctor --agent claude-desktop
```

In Claude Desktop, ask: *"Use the kicad MCP server to inspect the current project."*

## Troubleshooting examples

### Server does not appear in Claude Desktop

**Symptom:** Claude Desktop starts normally, but the `kicad` MCP server is not listed.

**Likely cause:** The config file is in the wrong location or Claude Desktop was not restarted after editing it.

**Fix:** Confirm the platform-specific `claude_desktop_config.json` path above, validate that the JSON contains `mcpServers.kicad`, then fully quit and reopen Claude Desktop.

### Claude reports invalid MCP config

**Symptom:** Claude Desktop shows a configuration error or refuses to load the MCP server.

**Likely cause:** The JSON has a trailing comma, missing quote, or mismatched brace.

**Fix:** Paste the config into a JSON validator, remove comments and trailing commas, and keep only one top-level `mcpServers` object.

### `uvx` or `kicad-mcp-pro` is not found

**Symptom:** Claude tries to start the server but reports that the command cannot be found.

**Likely cause:** `uv` is not installed or Claude Desktop is launched with a reduced PATH.

**Fix:** Install `uv`, confirm `uvx kicad-mcp-pro --help` works in a terminal, or replace `command` with the absolute path to `uvx` on your machine.

### Project path is wrong

**Symptom:** The server starts, but project inspection tools cannot find KiCad files.

**Likely cause:** `KICAD_MCP_PROJECT_DIR` points to a parent folder, a missing folder, or a path with user-specific shell shortcuts that Claude Desktop does not expand.

**Fix:** Use a full absolute path to the folder containing the `.kicad_pro` file. Avoid `~`, environment-variable-only paths, and private paths in shared screenshots.

### Write tools are unavailable

**Symptom:** Claude can inspect the project but cannot modify files.

**Likely cause:** The config intentionally uses `KICAD_MCP_OPERATING_MODE=readonly`.

**Fix:** Keep readonly mode for onboarding. Switch modes only after backing up the project and confirming you want the agent to make reviewed file changes.

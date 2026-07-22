# Agent quickstart matrix

Use this page when you want to connect one MCP-capable client quickly and start with a safe read-only KiCad workflow.

## Recommended first prompt

```text
Open the current KiCad project, inspect the schematic hierarchy, list ERC-relevant issues, render a schematic preview, and explain what changed without modifying files.
```

Keep the first run read-only. Switch to write mode only after the project is backed up and you are ready to review every modification.

## Client matrix

| Client | Setup doc | Config location | First validation |
| --- | --- | --- | --- |
| Claude Desktop | [Claude Desktop](claude-desktop.md) | `claude_desktop_config.json` | Ask Claude to inspect the current project without editing files. |
| Cursor | [Cursor](cursor.md) | `.cursor/mcp.json` | Use Agent mode and ask for a read-only ERC/DRC summary. |
| VS Code / Copilot | [VS Code Copilot](vscode-copilot.md) | `.vscode/mcp.json` | Command Palette → MCP: List Servers. |
| Windsurf | [Windsurf](windsurf.md) | `~/.codeium/windsurf/mcp_config.json` | Confirm the Cascade MCP panel shows the `kicad` server. |
| Cline | [Cline](cline.md) | Cline MCP settings or `~/.cline/mcp.json` | Confirm the Cline panel lists the server and tools. |
| OpenCode | [OpenCode](opencode.md) | `opencode.json` | Run `opencode mcp list`. |

## Copy-paste baseline config

Use `readonly` for the first connection:

```json
{
  "mcpServers": {
    "kicad": {
      "command": "uvx",
      "args": ["kicad-mcp-pro"],
      "env": {
        "KICAD_MCP_PROJECT_DIR": "/absolute/path/to/kicad/project",
        "KICAD_MCP_PROFILE": "default",
        "KICAD_MCP_OPERATING_MODE": "readonly"
      }
    }
  }
}
```

VS Code / Copilot uses `servers` instead of `mcpServers`; see the dedicated page for the exact shape.

## Expected output

A healthy first run should give the agent enough context to summarize:

- the active KiCad project or project path;
- schematic hierarchy and available board files;
- ERC/DRC-relevant findings when available;
- preview/render status when the runtime can produce visual evidence;
- clear warnings if KiCad CLI, project files, or rendering dependencies are unavailable.

## Safety defaults

- Keep `KICAD_MCP_OPERATING_MODE=readonly` for onboarding.
- Do not put tokens or private absolute paths in screenshots or shared configs.
- Treat rendered previews as evidence, not as engineering sign-off.
- For edit workflows, inspect the plan first, run preview/ ERC/DRC afterwards, and keep a human in the approval loop.

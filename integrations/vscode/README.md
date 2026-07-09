# VS Code / GitHub Copilot — KiCad MCP Integration

Connect [VS Code](https://code.visualstudio.com) and [GitHub Copilot](https://github.com/features/copilot) to KiCad via the `kicad-mcp-pro` MCP server.

## Quick Install

```bash
kicad-mcp-pro setup vscode
```

Or manually:

1. Copy `mcp.example.json` to `.vscode/mcp.json` in your project.
2. (Optional) Copy `copilot-instructions.md` to `.github/copilot-instructions.md`.
3. Restart VS Code.
4. Open the Command Palette → **MCP: List Servers** to verify.

## Configuration

VS Code MCP config supports:
- **stdio** servers (local) via `command` + `args`
- **HTTP** servers (remote) via `url` + `headers`
- **Sandboxing** for filesystem and network access on macOS/Linux
- **Inputs** for secure token prompts

## Copilot Instructions

The `copilot-instructions.md` file tells GitHub Copilot when and how to use the kicad MCP server. Place it in `.github/copilot-instructions.md` for repository-wide rules.

## Remote Configuration

For VS Code remote MCP with token auth:

```json
{
  "inputs": [
    {
      "type": "promptString",
      "id": "kicad-token",
      "description": "KiCad MCP Cloud Token",
      "password": true
    }
  ],
  "servers": {
    "kicadCloud": {
      "type": "http",
      "url": "https://mcp.kicad.example.com/mcp",
      "headers": {
        "Authorization": "Bearer ${input:kicad-token}"
      }
    }
  }
}
```

## Verification

```bash
kicad-mcp-pro doctor --agent vscode
```

## Security

- VS Code supports sandboxing for stdio MCP servers — enable `sandboxEnabled: true` to restrict filesystem and network access.
- Use `denyRead` for sensitive paths like `~/.ssh`.

# VS Code / GitHub Copilot Integration

## Quick Start

```bash
kicad-mcp-pro setup vscode
```

Or manually add `.vscode/mcp.json`:

```json
{
  "servers": {
    "kicad": {
      "type": "stdio",
      "command": "uvx",
      "args": ["kicad-mcp-pro"],
      "cwd": "${workspaceFolder}",
      "env": {
        "KICAD_MCP_PROJECT_DIR": "${workspaceFolder}",
        "KICAD_MCP_PROFILE": "default",
        "KICAD_MCP_OPERATING_MODE": "readonly"
      },
      "sandboxEnabled": true
    }
  }
}
```

## Copilot Instructions

Place `integrations/vscode/copilot-instructions.md` in `.github/copilot-instructions.md` for automatic KiCad-aware behavior.

## Verification

Command Palette → **MCP: List Servers** → verify `kicad` appears.

## Remote Config

```json
{
  "inputs": [{
    "type": "promptString",
    "id": "kicad-token",
    "description": "KiCad MCP Cloud Token",
    "password": true
  }],
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

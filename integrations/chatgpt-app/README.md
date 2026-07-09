# ChatGPT App — KiCad MCP Integration

Connect [ChatGPT](https://chatgpt.com) to KiCad via a custom GPT app powered by the KiCad MCP remote server.

## Architecture

ChatGPT Apps use the MCP Apps SDK, which provides:
- MCP server connectivity (remote HTTP/SSE)
- Optional web UI components rendered as iframes within ChatGPT
- JSON-RPC over postMessage bridge between ChatGPT and the web app

### Mode A — Public-safe (V1)
- No local filesystem access
- Upload KiCad project zip for analysis
- Cloud-based static analysis
- Report generation (DRC/ERC/manufacturing)
- Config snippet generation

### Mode B — Developer/Local Bridge (V2)
- User runs `kicad-mcp-pro bridge` on their machine
- ChatGPT app pairs with local bridge via pairing code
- Write tools require local approval
- Short-lived tokens and project access

## Quick Start

1. Enable **Developer Mode** in ChatGPT: Settings → Apps → Advanced → Developer mode
2. Create a new app: Enter the MCP server URL
3. Configure OAuth or no-auth for development
4. The app appears in your ChatGPT interface

## App Files

| File | Purpose |
|------|---------|
| `apps-sdk/package.json` | Node.js package with dependencies |
| `apps-sdk/src/server.ts` | MCP server implementation |
| `apps-sdk/public/kicad-dashboard.html` | Project overview widget |
| `apps-sdk/public/project-review.html` | Board health dashboard |
| `apps-sdk/public/manufacturing-report.html` | Manufacturing checklist widget |

## UI Widgets

- **Project Overview Card** — board info, KiCad version, file paths
- **Board Health Dashboard** — ERC/DRC status, quality gates
- **ERC/DRC Issue Table** — grouped by severity with explanations
- **BOM Summary** — component count, status, MPN coverage
- **Manufacturing Export Checklist** — step-by-step release tracker
- **Local Setup Wizard** — config snippet for Codex/Claude/Gemini/OpenCode

## Security

- Remote tools cannot access your local machine directly
- Uploaded project archives may contain untrusted content
- See `docs/agents/security.md` for prompt injection guidance

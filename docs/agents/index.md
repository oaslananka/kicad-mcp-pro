# KiCad MCP — AI Agent Integration Guide

kiCad-mcp-pro is an MCP server that exposes KiCad PCB design capabilities as tools for AI agents: board inspection, schematic/PCB review, DRC/ERC, DFM, manufacturing export, SPICE simulation, and more.

## Supported Agents

| Agent | Local STDIO | Remote HTTP | Skills | App UI |
|-------|------------|-------------|--------|--------|
| [Claude Code](claude-code.md) | ✅ Supported | ✅ Supported | ✅ Supported | — |
| [Codex CLI](codex.md) | ✅ Supported | ✅ Supported | Via AGENTS.md | — |
| [Gemini CLI](gemini-cli.md) | ✅ Supported | ✅ Supported | — | — |
| [OpenCode](opencode.md) | ✅ Supported | ✅ Supported | — | ✅ Plugin |
| [VS Code / Copilot](vscode-copilot.md) | ✅ Supported | ✅ Supported | — | Experimental |
| [Cursor](cursor.md) | ✅ Supported | ⚠️ Verify | ✅ Supported | — |
| [Claude Desktop](claude-desktop.md) | ✅ Supported | — | — | — |
| [.mcpb bundle](mcpb.md) | ✅ Supported | — | — | ✅ 1-file install |
| [Claude.ai Web](claude-ai.md) | ❌ No | ✅ Supported | — | Limited |
| [ChatGPT Web](chatgpt-app.md) | ❌ No | ✅ Supported | — | ✅ Apps SDK |
| [Antigravity](antigravity.md) | ⚠️ Verify | ✅ Supported | — | — |
| [Cline](cline.md) | ✅ Supported | ✅ Supported | ✅ Reusable | — |
| [Windsurf](windsurf.md) | ✅ Supported | ✅ Supported | — | — |
| [Continue](continue.md) | ✅ Supported | ✅ Supported | — | — |
| [Zed](zed.md) | ✅ Supported | ✅ Supported | — | — |

## Quick Start

For a client-by-client copy-paste setup overview, see the [Quickstart Matrix](quickstart.md).


```bash
# Install
pipx install kicad-mcp-pro

# Run diagnostics
kicad-mcp-pro doctor

# Generate config for your agent
kicad-mcp-pro mcp-config generate --client claude

# Or use the setup wizard
kicad-mcp-pro setup
```

## Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│                    AI Agent Host                         │
│  (Claude Code, Codex, Gemini CLI, ChatGPT, etc.)        │
└──────────┬──────────────────────────────────┬───────────┘
           │ STDIO / HTTP                     │ HTTP
           ▼                                  ▼
┌──────────────────────┐         ┌──────────────────────────┐
│  Local KiCad MCP     │         │  Remote KiCad MCP Cloud  │
│  (uvx kicad-mcp-pro) │         │  (Public HTTPS endpoint) │
│  Full tool access    │         │  Read-only tools         │
│  Direct file access  │         │  Upload analysis         │
└──────────────────────┘         └──────────────────────────┘
```

## Deployment Profiles

See `integrations/common/profiles.md` for the four deployment profiles:
1. **Local STDIO** — maximum capability, direct KiCad CLI access
2. **Local HTTP** — loopback-only for IDE integration
3. **Remote Cloud** — public HTTPS for ChatGPT/Claude.ai web
4. **Hybrid Bridge** — cloud + local bridge (V2)

## Security

> **Always start with read-only mode.** Enable write tools only for trusted projects.

- Destructive tools require explicit user approval
- Remote apps cannot directly access your local KiCad installation
- Uploaded project archives may contain untrusted content
- See [security.md](security.md) for detailed guidance

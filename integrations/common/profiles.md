# KiCad MCP Deployment Profiles

## 1. Local STDIO Profile

**Targets:** Claude Code, Codex CLI, Gemini CLI, OpenCode local, Cursor, VS Code Copilot, Claude Desktop, Antigravity

**Command:** `uvx kicad-mcp-pro`

**Features:**
- Direct KiCad CLI access
- Full filesystem access (within workspace)
- ERC/DRC/DFM, exports, routing
- Git integration for checkpoints
- Write tools require approval

**Default mode:** `readonly` / `analysis`

**Required env:** `KICAD_MCP_PROJECT_DIR`

## 2. Local Streamable HTTP Profile

**Targets:** VS Code, Cursor, Gemini CLI, Claude Code, OpenCode, local UI dashboard

**Command:** `kicad-mcp-pro serve --transport http --host 127.0.0.1 --port 8765`

**Features:**
- Loopback-only for security
- CORS allowlist
- Same tool set as STDIO
- No OAuth (localhost trusted)

## 3. Remote MCP Cloud Profile

**Targets:** ChatGPT web, Claude.ai web, Claude API MCP, OpenAI API, Gemini remote

**Endpoint:** `https://mcp.kicad.example.com/mcp`

**Features:**
- Public HTTPS endpoint
- Streamable HTTP with SSE fallback
- OAuth 2.1 / PKCE
- Read-only tools for public access
- Project upload analysis (no local filesystem)
- Containerized KiCad CLI for exports

**V1 scope:** Read-only project/package analysis, doc search, report generation.

## 4. Hybrid Local Bridge Profile

**Targets:** ChatGPT web + local KiCad, Claude.ai web + local KiCad

**Architecture:**
- Cloud MCP endpoint handles auth and session
- Local bridge daemon on user machine
- Secure pairing code
- Reverse tunnel / WebSocket (no open ports)
- Local approval for destructive tools
- Project files stay on user machine

**Status:** V2 design. Not default in first release.

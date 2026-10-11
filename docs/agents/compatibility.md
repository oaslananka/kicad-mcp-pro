# Agent Compatibility Matrix

## Feature Support

| Agent | Local STDIO | Remote HTTP | Skills/AGENTS.md | App UI | OAuth | Tool Filtering |
|-------|------------|-------------|-----------------|--------|-------|----------------|
| Claude Code | ✅ | ✅ | ✅ | — | ✅ | ✅ include/exclude |
| Codex CLI | ✅ | ✅ | ✅ AGENTS.md + Agent Skills | — | — | ✅ enabled/disabled |
| Gemini CLI | ✅ | ✅ | ✅ Agent Skills (host-dependent) | — | ✅ | ✅ include/exclude |
| OpenCode | ✅ | ✅ | ✅ AGENTS.md | ✅ Plugin | ✅ | ✅ glob patterns |
| VS Code/Copilot | ✅ | ✅ | ✅ Copilot instructions + Agent Skills | ⚠️ Experimental | ✅ | ✅ sandbox |
| Cursor | ✅ | ⚠️ Verify | ✅ Rules + Skills | — | — | ⚠️ Limited |
| Claude Desktop | ✅ | — | — | — | — | — |
| Claude.ai Web | ❌ | ✅ | ⚠️ Account feature | ⚠️ Limited | ✅ | ✅ tool allowlist |
| ChatGPT Web | ❌ | ✅ | — | ✅ Apps SDK | ✅ | ✅ tool allowlist |
| Antigravity | ⚠️ Verify | ✅ | — | — | ✅ | — |

## Notes

- **Local STDIO** requires `uvx kicad-mcp-pro` or `python -m kicad_mcp`
- **Remote HTTP** requires a publicly accessible HTTPS endpoint with Streamable HTTP
- **Skills** are Agent Skills standard format (SKILL.md with references)
- **App UI** refers to custom UI components within the agent interface
- **Tool Filtering** is the ability to limit which MCP tools are exposed

## Protocol Support

The table below describes **client-side transport feature support**, not
server conformance tested in this repository. The maintained Codex examples
include separate local stdio and HTTP configurations; older no-HTTP claims
must not be interpreted as the current integration policy. A real-host smoke
must be recorded before marking a client release as independently verified.

| Agent | STDIO | SSE | Streamable HTTP | OAuth 2.1 |
|-------|-------|-----|-----------------|-----------|
| Claude Code | ✅ | ✅ | ✅ | ✅ |
| Claude Desktop | ✅ | ❌ | ❌ | ❌ |
| Codex CLI | ✅ | ❌ | ✅ | Verify per host |
| Gemini CLI | ✅ | ✅ | ✅ | ✅ |
| OpenCode | ✅ | ❌ | ✅ | ✅ |
| VS Code | ✅ | ✅ | ✅ | ✅ |
| Cursor | ✅ | ❌ | ✅ | ❌ |
| ChatGPT Web | ❌ | ✅ | ✅ | ✅ |
| Claude.ai Web | ❌ | ✅ | ✅ | ✅ |
| Antigravity | ✅ | ✅ | ✅ | ✅ |


## Evidence confidence (October 2026)

The entries above describe intended/known integration capabilities and should
not be read as a claim that every host has been independently installed and
exercised in CI. The machine-validated **static** host catalog lives in
`integrations/common/agent-host-evidence.json`. Actual supported build and
runtime smoke evidence follows [host verification](host-verification.md).

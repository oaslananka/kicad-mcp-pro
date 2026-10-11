# KiCad MCP Pro — Gemini CLI extension (pilot)

This **local, opt-in** Gemini CLI extension bundles the versioned KiCad MCP
server entry point and seven portable Agent Skills. It is **not** yet a verified
public extension-gallery submission. It never installs KiCad, Python or `uv`.

## Prerequisites

Install [Gemini CLI](https://geminicli.com/docs/),
[uv/uvx](https://docs.astral.sh/uv/getting-started/installation/) and a
[compatible KiCad](../../../docs/agents/compatibility.md) separately.
Do not use untrusted projects in write mode; the extension config enforces
`KICAD_MCP_OPERATING_MODE=readonly`.

## Local test install

From the repository root, in a trusted shell:

```bash
gemini extensions install ./integrations/gemini-cli/kicad-mcp-pro
gemini extensions list
```

Restart Gemini CLI, run `/mcp`, and inspect `kicad` discovery. In a trusted
KiCad fixture project, request a **read-only** summary and ERC/DRC report;
confirm a write tool is unavailable. Record exact Gemini version, OS,
transport, server version, capability list and sanitized tool result before
claiming host compatibility. The CI manifest tests are **not** such a smoke.

When testing a different commit, reinstall/update the installed extension:
Gemini copies rather than live-links local extension sources.

Skills under this extension's `skills/` directory are **generated** from
`skills/` at the repo root. Edit canonical skill definitions only and run
`python scripts/sync_agent_skills.py --write` before committing.

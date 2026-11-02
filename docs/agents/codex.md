# Codex CLI Integration

## Quick Start

```bash
uvx kicad-mcp-pro quickstart --agent codex
```

Or add the verified `[mcp_servers.kicad]` block to `~/.codex/config.toml`.
Merge the named table; do not replace the entire configuration or use the
legacy `[[mcp_servers]]` array format. Advanced fields depend on your Codex
version; see the [official MCP documentation](https://learn.chatgpt.com/docs/extend/mcp?surface=cli):

```toml
[mcp_servers.kicad]
command = "uvx"
args = ["kicad-mcp-pro", "--transport", "stdio"]
startup_timeout_sec = 20
tool_timeout_sec = 120

[mcp_servers.kicad.env]
KICAD_MCP_PROFILE = "default"
KICAD_MCP_OPERATING_MODE = "readonly"
# KICAD_MCP_PROJECT_DIR = "/absolute/path/to/kicad-project"
```

## Verification

Run: `kicad-mcp-pro doctor`

The kicad tools appear automatically in Codex CLI when the config is present.

## Smoke Test Prompt

> Use the kicad MCP server. Inspect this KiCad project, identify the board, schematic, KiCad version, run the available quality gates, and summarize whether the project is ready for PCB review. Do not modify files.

## Optional remote OAuth

Local stdio does not require a KiCad Cloud account. For an independently
configured OAuth-capable remote server named `kicad-cloud`, authenticate with
`codex mcp login kicad-cloud`. On a terminal without a browser, use
`codex mcp login kicad-cloud --no-browser` and follow the displayed instructions.
This authenticates that MCP client; device pairing and local project permissions
remain separate. See the [official MCP guide](https://learn.chatgpt.com/docs/extend/mcp?surface=cli).

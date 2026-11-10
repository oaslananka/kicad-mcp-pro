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

## Project-local setup

Codex reads a single user config at `~/.codex/config.toml` (it has no separate
project scope), so pin the project path in the server's `env` table. Use
`uvx`, which fetches the published package, and set `KICAD_MCP_NGSPICE_CLI`
when you also run `sim_run_*` analyses and auto-detection misses your install:

```toml
[mcp_servers.kicad]
enabled = true
command = "uvx"
args = ["kicad-mcp-pro", "--transport", "stdio"]
startup_timeout_sec = 20
tool_timeout_sec = 120

[mcp_servers.kicad.env]
KICAD_MCP_PROJECT_DIR = "/absolute/path/to/kicad-project"
KICAD_MCP_TRANSPORT = "stdio"
KICAD_MCP_PROFILE = "default"
KICAD_MCP_OPERATING_MODE = "readonly"
# KICAD_MCP_NGSPICE_CLI = "/Applications/KiCad/KiCad.app/Contents/MacOS/ngspice"
```

The `kicad-mcp-pro setup codex --scope user --write` command writes this same
shape. Python 3.13+ and KiCad 10.x are prerequisites; see
[Install](install.md) for the full list.

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

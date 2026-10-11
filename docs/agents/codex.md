# Codex CLI Integration

## Quick Start

```bash
kicad-mcp-pro setup codex
```

Or add the verified `[mcp_servers.kicad]` block to `~/.codex/config.toml`.
Do not use legacy `[[mcp_servers]]`, `default_tools_approval_mode`, or `cwd`
fields; they are not part of the maintained Codex example:

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

Run: `kicad-mcp-pro doctor --agent codex`

The kicad tools appear automatically in Codex CLI when the config is present.

## Smoke Test Prompt

> Use the kicad MCP server. Inspect this KiCad project, identify the board, schematic, KiCad version, run the available quality gates, and summarize whether the project is ready for PCB review. Do not modify files.

# Agent Installation Guide

The canonical, minimal install path lives in [`../installation.md`](../installation.md).
This page adds the agent-specific setup (MCP client config, environment variables).

## Prerequisites

- **Python 3.13+** and `uvx` (or `pipx`)
- **KiCad 10.0+** for `kicad-cli` and full tool access (file-level read and migration
  support for 8.x; see the compatibility matrix)
- Internet access for package installation

## Install kicad-mcp-pro

### With pipx (recommended)

```bash
pipx install kicad-mcp-pro
```

### With uvx (no install)

```bash
uvx kicad-mcp-pro
```

### With pip

```bash
pip install kicad-mcp-pro
```

## Configure an agent without losing existing settings

**Recommended (single supported writer):** the Python CLI merges only KiCad MCP
settings into the selected agent's existing JSON/TOML configuration. It
validates the result, creates a dated restorable backup, and atomically replaces
the file. Preview first, then explicitly opt in to the write:

```bash
kicad-mcp-pro setup cursor --scope project --mode readonly
kicad-mcp-pro setup cursor --scope project --mode readonly --write
# Or for a user-level Codex config:
kicad-mcp-pro setup codex --scope user --mode readonly --write
```

The legacy `node integrations/common/install-kicad-mcp.mjs` entry point now
**delegates to this same Python writer** rather than copying an entire sample
file over existing settings. It is only a compatibility wrapper; it requires
`kicad-mcp-pro` on `PATH`. `--dry-run` prints a non-writing preview. It does not
accept the old `local` scope: use the Python-supported `project` scope instead.
For restoration use `kicad-mcp-pro setup-backups` and `setup-restore`. A config
write does not prove real agent/KiCad connectivity; run the doctor and host
smoke checks separately.

## Verify Installation

```bash
kicad-mcp-pro doctor
```

Expected output includes Python version, uvx availability, kicad-cli status, project directory, and tool count.

## Set Up for Your Agent

Choose your agent for detailed setup instructions:

- [Claude Code](claude-code.md) — `claude mcp add` or `.mcp.json`
- [Codex CLI](codex.md) — `config.toml` in `~/.codex/`
- [Gemini CLI](gemini-cli.md) — `settings.json` in `~/.gemini/`
- [OpenCode](opencode.md) — `opencode.json` in project root
- [VS Code / Copilot](vscode-copilot.md) — `.vscode/mcp.json`
- [Cursor](cursor.md) — `.cursor/mcp.json` + Rules
- [Claude Desktop](claude-desktop.md) — `claude_desktop_config.json`
- [Claude.ai Web](claude-ai.md) — Remote connector (public endpoint required)
- [ChatGPT Web](chatgpt-app.md) — ChatGPT Developer Mode app (V1: remote only)
- [Antigravity](antigravity.md) — `~/.gemini/config/mcp_config.json`

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `KICAD_MCP_PROJECT_DIR` | Yes | Path to KiCad project directory |
| `KICAD_MCP_PROFILE` | No | Server profile (default: `default`, 24 tools) |
| `KICAD_MCP_OPERATING_MODE` | No | `readonly`, `write`, `manufacturing`, `experimental` |
| `KICAD_MCP_KICAD_CLI` | No | Path to kicad-cli binary |
| `KICAD_MCP_OUTPUT_DIR` | No | Output directory for exports |

## Troubleshooting

See [troubleshooting.md](troubleshooting.md) for common issues.

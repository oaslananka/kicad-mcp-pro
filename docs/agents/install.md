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

## Fast local setup

For the shortest local-first path, open a terminal in the KiCad project folder and run:

```bash
uvx kicad-mcp-pro quickstart
```

The command detects supported agent CLIs on `PATH` and a KiCad project directory.
It asks which agent to use when multiple are found, or asks for a project directory
when none is found in the current folder. It checks `uvx` before writing, merges
only the selected agent's KiCad MCP entry in **read-only** mode, and backs up
existing settings. The absolute launcher path is saved so GUI PATH differences
do not silently select another executable. It then reads that saved entry and
verifies its actual command over stdio with `kicad_get_server_info`.

On supported hosts it also installs the seven bundled KiCad skills, including
their references and scripts. Claude Code, Codex, Gemini, OpenCode, Cursor and
VS Code have explicit discovery locations. Claude Desktop and Antigravity report
that portable skill installation is unavailable; their MCP setup still works.
Edited or conflicting skills are preserved and block skill installation before
the MCP config is written. Use `--no-skills` when a native plugin/extension
already supplies the skills or when you want MCP configuration only.

No Cloud login, account, API key, browser session or remote service is used. Restart
or reload the selected agent after a successful setup. To choose explicitly:

```bash
uvx kicad-mcp-pro quickstart --agent codex --project-dir /path/to/kicad-project
```

This verifies the saved launch command, not the actual agent's skill discovery
or native KiCad availability. In the selected agent, ask: **Inspect this KiCad
project without modifying files.** Review the project identity, CLI/IPC readiness
and actual tool response before starting work. Missing IPC does not imply that
file-backed KiCad CLI operations are unavailable.

Manage the bundled skills separately:

```bash
uvx kicad-mcp-pro skills status --agent cursor --project-dir /path/to/kicad-project
uvx kicad-mcp-pro skills install --agent cursor --project-dir /path/to/kicad-project
uvx kicad-mcp-pro skills remove --agent cursor --project-dir /path/to/kicad-project
```

Installation is repeatable. Matching existing skills are reused. Updates to
unchanged installer-owned skills keep backups under the host configuration
directory's `.kicad-mcp-pro-skill-backups/`, outside skill discovery. Removal
preserves unrelated, unowned and edited workflows, as well as backups. These
commands manage skill files only; MCP configuration and Cloud permissions have
their own lifecycle. Native plugins should be updated or removed in the host's
plugin manager instead of being installed a second time through quickstart.
Skill commands use the resources bundled with the CLI version you run. Update
that package through your installation manager before refreshing skills; the
installer does not download independent, unversioned workflow instructions.

Use `kicad-mcp-pro setup-backups <agent>` and `kicad-mcp-pro setup-restore <agent>`
to inspect or restore a previous configuration. Cloud access is a separate,
optional setup and is never required for local stdio use.

## Native plugin or extension alternative

For a trusted source checkout, Claude Code can validate and load the bundled
skills and MCP server with `claude plugin validate .` and `claude --plugin-dir .`.
Portable Agent Plugins hosts can import the root `plugin.json`, `mcp.json`, and
`skills/` package. The portable MCP launcher pins the matching published server
version; `uv` and KiCad are prerequisites. This source package is not evidence
of public marketplace approval or real-host compatibility.

Gemini users can choose the [native extension pilot](https://github.com/oaslananka/kicad-mcp-pro/tree/main/integrations/gemini-cli/kicad-mcp-pro).
Choose either a native package or quickstart for the same host to avoid duplicate
servers and skills. A plugin installed on your computer does not automatically
become available in a remote AI execution environment.

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

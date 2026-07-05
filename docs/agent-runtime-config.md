# Agent Runtime Configuration

This document gives copyable configuration examples for running KiCad MCP Pro from popular MCP-capable agent runtimes.

## Claude Code

The repository includes both:

- `.claude-plugin/plugin.json` with a native `mcpServers` entry.
- `.mcp.json` with the same MCP server definition for project-local Claude Code usage.

Validate the plugin locally:

```bash
claude plugin validate .
```

Run Claude Code with this plugin directory for one session:

```bash
claude --plugin-dir .
```

## Codex CLI

Use `.codex/config.example.toml` as a starting point. Copy the `[[mcp_servers]]` block into your Codex config file and adjust command arguments if needed.

## VS Code / GitHub Copilot

Use `.vscode/mcp.example.json` as a workspace MCP configuration example. If your VS Code profile already has MCP servers configured globally, copy only the `kicad-mcp-pro` server block.

## OpenCode

Use `opencode.example.jsonc` as a project-level OpenCode MCP configuration example. Copy it to `opencode.json` in a working project, or merge the `mcp` block into an existing OpenCode config.

OpenCode discovers project-local skills from `.opencode/skills/<name>/SKILL.md`, so this repository mirrors the KiCad skills there for OpenCode-native loading.

Local MCP server command:

```bash
uvx kicad-mcp-pro --transport stdio
```

Typical prompt hint:

```text
Use the kicad-mcp-pro MCP tools and the pcb-design skill to review this KiCad board.
```

## Cursor and other MCP clients

Most MCP-compatible clients can use the same stdio launch command:

```bash
uvx kicad-mcp-pro --transport stdio
```

## Validation checklist

1. Confirm the command starts: `uvx kicad-mcp-pro --help`.
2. Validate plugin metadata: `claude plugin validate .`.
3. Start an MCP-capable client with the configured server.
4. Call a safe read-only diagnostic tool such as `kicad_get_server_info` or `kicad_get_project_info`.
5. Use the KiCad skills only after the active project path and required KiCad installation state are clear.

## Safety

KiCad MCP Pro is an engineering assistant, not a manufacturing sign-off authority. ERC, DRC, DFM, fabrication exports, and all generated design changes require human engineering review.

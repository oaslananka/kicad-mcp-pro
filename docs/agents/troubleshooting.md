# Troubleshooting Guide

## Common Issues

### "uvx not found"

Install [uv](https://docs.astral.sh/uv/):
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### "kicad-cli not found"

Install KiCad or set the path explicitly:
```bash
export KICAD_MCP_KICAD_CLI=/usr/bin/kicad-cli
```

### "MCP server not starting"

1. Check Python version: `python3 --version` (need 3.10+)
2. Run doctor: `kicad-mcp-pro doctor`
3. Check for port conflicts (HTTP mode)
4. Verify project directory exists

### "Tools not showing up in agent"

1. Agent-specific:
   - **Claude Code:** Run `/mcp` to verify. Check `.mcp.json` or `~/.claude.json`
   - **Codex CLI:** Check `~/.codex/config.toml` for `[mcp_servers.kicad]`
   - **Gemini CLI:** Run `/mcp`. Check `~/.gemini/settings.json`
   - **OpenCode:** Run `opencode mcp list`. Check `opencode.json`
   - **VS Code:** **MCP: List Servers** command palette
   - **Cursor:** Check `.cursor/mcp.json`
   - **Claude Desktop:** Check `claude_desktop_config.json` for syntax errors
   - **ChatGPT:** Ensure Developer Mode is enabled

2. Check startup timeout: Large projects may need longer startup
3. Check for duplicate server entries

### "Write tools not working"

1. Check operating mode: Should be `write` or `manufacturing`
2. Check tool filtering: Is the tool in the allowed list?
3. Check agent approval: Is `default_tools_approval_mode` set to `prompt`?

### Windows-Specific Issues

1. **Path separators:** Use forward slashes or escaped backslashes in config
2. **uvx location:** `uvx` may be in `%USERPROFILE%\.local\bin\uvx`
3. **kicad-cli path:** Default: `C:\Program Files\KiCad\bin\kicad-cli.exe`
4. **stdout pollution:** MCP protocol requires clean stdout. Use `--transport http` if debug logging interferes

### macOS-Specific Issues

1. **Claude Desktop config path:** `~/Library/Application Support/Claude/claude_desktop_config.json`
2. **kicad-cli path:** Check `/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli`

### Linux-Specific Issues

1. **Claude Desktop config path:** `~/.config/Claude/claude_desktop_config.json`
2. **kicad-cli path:** Usually `/usr/bin/kicad-cli`

## Running Doctor

```bash
# Full diagnostics
kicad-mcp-pro doctor

# Agent-specific check
kicad-mcp-pro doctor | grep "Config for"
# or use the common doctor script
python integrations/common/doctor.py --agent claude-code

# Machine-readable output
kicad-mcp-pro doctor --json

# Write diagnostic bundle for support
kicad-mcp-pro doctor --bundle /tmp/kicad-bundle.zip
```

## Getting Help

- GitHub Issues: https://github.com/oaslananka/kicad-mcp-pro/issues
- Documentation: docs/
- Run `kicad-mcp-pro doctor --bundle bundle.zip` and attach to your issue

# Client Configuration

KiCad MCP Pro works with MCP clients that can start a local `stdio` server or connect to a
Streamable HTTP endpoint. The most portable setup is local `stdio` with `uvx`.

Replace `/absolute/path/to/your/kicad-project` with your KiCad project directory. You can
omit `KICAD_MCP_PROJECT_DIR` and call `kicad_set_project()` from the client instead, but
setting it once in the client config gives you a persistent default project.

## Recommended Local Server

Use this command in clients that ask for a command and arguments:

```text
command: uvx
args: ["kicad-mcp-pro"]
```

Recommended environment:

```text
KICAD_MCP_PROJECT_DIR=/absolute/path/to/your/kicad-project
KICAD_MCP_PROFILE=default
KICAD_MCP_OPERATING_MODE=readonly
```

The default `default` profile is a bounded 24-tool review surface. Use `review` for the
same explicit read-only contract, `build` with `KICAD_MCP_OPERATING_MODE=write` for
plan/preview/apply/verify/rollback workflows, and `release` with
`KICAD_MCP_OPERATING_MODE=manufacturing` for human-gated manufacturing handoff. Use
`expert` or the backward-compatible `full` profile only when the client genuinely needs
the complete catalog. Existing focused profiles such as `pcb_only`, `schematic_only`,
`manufacturing`, `high_speed`, `power`, `simulation`, and `analysis` remain available.
Profiles select the discovery surface; `KICAD_MCP_OPERATING_MODE` is an independent risk
gate applied on top.

## CLI Setup Command Variants

Use these command variants when the client can register MCP servers from its CLI. Use the
JSON or TOML config examples below for clients that only read config files.

Linux and macOS:

```bash
codex mcp add kicad \
  --env KICAD_MCP_PROJECT_DIR=/absolute/path/to/your/kicad-project \
  --env KICAD_MCP_PROFILE=pcb_only \
  --env KICAD_MCP_OPERATING_MODE=readonly \
  -- uvx kicad-mcp-pro

claude mcp add --transport stdio --scope project \
  --env KICAD_MCP_PROJECT_DIR=/absolute/path/to/your/kicad-project \
  --env KICAD_MCP_PROFILE=pcb_only \
  --env KICAD_MCP_OPERATING_MODE=readonly \
  kicad -- uvx kicad-mcp-pro

gemini mcp add --scope project --transport stdio \
  -e KICAD_MCP_PROJECT_DIR=/absolute/path/to/your/kicad-project \
  -e KICAD_MCP_PROFILE=pcb_only \
  -e KICAD_MCP_OPERATING_MODE=readonly \
  kicad uvx kicad-mcp-pro
```

Windows PowerShell:

```powershell
codex mcp add kicad `
  --env 'KICAD_MCP_PROJECT_DIR=C:\absolute\path\to\your\kicad-project' `
  --env 'KICAD_MCP_PROFILE=pcb_only' `
  --env 'KICAD_MCP_OPERATING_MODE=readonly' `
  -- uvx kicad-mcp-pro

claude mcp add --transport stdio --scope project `
  --env 'KICAD_MCP_PROJECT_DIR=C:\absolute\path\to\your\kicad-project' `
  --env 'KICAD_MCP_PROFILE=pcb_only' `
  --env 'KICAD_MCP_OPERATING_MODE=readonly' `
  kicad -- uvx kicad-mcp-pro

gemini mcp add --scope project --transport stdio `
  -e 'KICAD_MCP_PROJECT_DIR=C:\absolute\path\to\your\kicad-project' `
  -e 'KICAD_MCP_PROFILE=pcb_only' `
  -e 'KICAD_MCP_OPERATING_MODE=readonly' `
  kicad uvx kicad-mcp-pro
```

## VS Code And GitHub Copilot

VS Code uses `.vscode/mcp.json` for workspace-level configuration and a user profile MCP
configuration for global setup. GitHub Copilot in VS Code uses the same MCP server setup.
The repository ships `.vscode/mcp.example.json` as the copyable workspace example; place
the same shape in `.vscode/mcp.json` for your own project.

`.vscode/mcp.example.json`:

```json
{
  "servers": {
    "kicad": {
      "type": "stdio",
      "command": "uvx",
      "args": ["kicad-mcp-pro"],
      "env": {
        "KICAD_MCP_PROJECT_DIR": "/absolute/path/to/your/kicad-project",
        "KICAD_MCP_PROFILE": "pcb_only",
        "KICAD_MCP_OPERATING_MODE": "readonly"
      }
    }
  }
}
```

Use an absolute KiCad project path for `KICAD_MCP_PROJECT_DIR`. Some VS Code MCP setups do
not expand `${workspaceFolder}` and may fail at server startup.

## Destination Paths

Copy the example into the client-owned config file. Keep repository examples inert by
leaving their `.example.*` filenames unchanged.
The Windows paths use `%USERPROFILE%` and `%APPDATA%` conventions used on Windows 11 and
current supported Windows releases.

| Client                     | Linux/macOS destination                                                                                          | Windows destination                                                          |
| -------------------------- | ---------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------- |
| VS Code and GitHub Copilot | `<project>/.vscode/mcp.json`, or the user-profile config opened by `MCP: Open User Configuration`                | `<project>\.vscode\mcp.json`, or the user-profile config opened from VS Code |
| Codex CLI / IDE extension  | `~/.codex/config.toml`, or a trusted `<project>/.codex/config.toml`                                              | `%USERPROFILE%\.codex\config.toml`, or `<project>\.codex\config.toml`        |
| Claude Code                | `<project>/.mcp.json`, or use `claude mcp add --scope project`                                                   | `<project>\.mcp.json`, or use `claude mcp add --scope project`               |
| Claude Desktop             | macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`; Linux users should use Claude Code MCP | `%APPDATA%\Claude\claude_desktop_config.json`                                |
| Cursor                     | `<project>/.cursor/mcp.json` or `~/.cursor/mcp.json`                                                             | `<project>\.cursor\mcp.json` or `%USERPROFILE%\.cursor\mcp.json`             |
| Gemini CLI                 | `~/.gemini/settings.json` or `<project>/.gemini/settings.json`                                                   | `%USERPROFILE%\.gemini\settings.json` or `<project>\.gemini\settings.json`   |
| Generic stdio client       | The client's MCP config file                                                                                     | The client's MCP config file                                                 |
| Generic HTTP client        | The client's remote/HTTP MCP config file                                                                         | The client's remote/HTTP MCP config file                                     |

## Codex CLI And Codex IDE Extension

Codex stores MCP servers in `~/.codex/config.toml` or a trusted project-scoped
`.codex/config.toml`.

CLI setup:

```bash
codex mcp add kicad \
  --env KICAD_MCP_PROJECT_DIR=/absolute/path/to/your/kicad-project \
  --env KICAD_MCP_PROFILE=pcb_only \
  --env KICAD_MCP_OPERATING_MODE=readonly \
  -- uvx kicad-mcp-pro
```

`~/.codex/config.toml`:

```toml
[mcp_servers.kicad]
command = "uvx"
args = ["kicad-mcp-pro"]
startup_timeout_sec = 20
tool_timeout_sec = 120

[mcp_servers.kicad.env]
KICAD_MCP_PROJECT_DIR = "/absolute/path/to/your/kicad-project"
KICAD_MCP_PROFILE = "pcb_only"
KICAD_MCP_OPERATING_MODE = "readonly"
```

## Claude Desktop

Add the server to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "kicad": {
      "command": "uvx",
      "args": ["kicad-mcp-pro"],
      "env": {
        "KICAD_MCP_PROJECT_DIR": "/absolute/path/to/your/kicad-project",
        "KICAD_MCP_PROFILE": "pcb_only",
        "KICAD_MCP_OPERATING_MODE": "readonly"
      }
    }
  }
}
```

## Claude Code

Use KiCad MCP Pro 1.0.0 or newer for Claude Code `stdio` setups. That release defers
heavy tool registration until after the MCP `initialize` handshake, avoiding startup races
on slower WSL or cold KiCad environments.

Project-scoped `.mcp.json`:

```json
{
  "mcpServers": {
    "kicad": {
      "command": "uvx",
      "args": ["kicad-mcp-pro"],
      "env": {
        "KICAD_MCP_PROJECT_DIR": "/absolute/path/to/your/kicad-project",
        "KICAD_MCP_PROFILE": "pcb_only",
        "KICAD_MCP_OPERATING_MODE": "readonly"
      }
    }
  }
}
```

CLI setup:

```bash
claude mcp add kicad \
  --scope project \
  --env KICAD_MCP_PROJECT_DIR=/absolute/path/to/your/kicad-project \
  --env KICAD_MCP_PROFILE=pcb_only \
  --env KICAD_MCP_OPERATING_MODE=readonly \
  -- uvx kicad-mcp-pro
```

## Cursor

Use `.cursor/mcp.json` for project configuration or `~/.cursor/mcp.json` for global
configuration:

```json
{
  "mcpServers": {
    "kicad": {
      "type": "stdio",
      "command": "uvx",
      "args": ["kicad-mcp-pro"],
      "env": {
        "KICAD_MCP_PROJECT_DIR": "/absolute/path/to/your/kicad-project",
        "KICAD_MCP_PROFILE": "pcb_only",
        "KICAD_MCP_OPERATING_MODE": "readonly"
      }
    }
  }
}
```

## Gemini CLI

Add the server to `~/.gemini/settings.json`:

```json
{
  "mcpServers": {
    "kicad": {
      "command": "uvx",
      "args": ["kicad-mcp-pro"],
      "env": {
        "KICAD_MCP_PROJECT_DIR": "/absolute/path/to/your/kicad-project",
        "KICAD_MCP_PROFILE": "pcb_only",
        "KICAD_MCP_OPERATING_MODE": "readonly"
      },
      "timeout": 120000
    }
  }
}
```

## Antigravity And Other MCP Clients

If your client accepts the common `mcpServers` JSON shape, use this as the starting point:

```json
{
  "mcpServers": {
    "kicad": {
      "type": "stdio",
      "command": "uvx",
      "args": ["kicad-mcp-pro"],
      "env": {
        "KICAD_MCP_PROJECT_DIR": "/absolute/path/to/your/kicad-project",
        "KICAD_MCP_PROFILE": "pcb_only",
        "KICAD_MCP_OPERATING_MODE": "readonly"
      }
    }
  }
}
```

Client-specific behavior can vary. If the client supports only HTTP servers, use the HTTP
setup below.

## Streamable HTTP Setup

Start KiCad MCP Pro as an HTTP server:

Linux and macOS:

```bash
KICAD_MCP_PROJECT_DIR=/absolute/path/to/your/kicad-project \
KICAD_MCP_PROFILE=pcb_only \
KICAD_MCP_OPERATING_MODE=readonly \
uvx kicad-mcp-pro --transport http --host 127.0.0.1 --port 3334
```

Windows PowerShell:

```powershell
$Env:KICAD_MCP_PROJECT_DIR = 'C:\absolute\path\to\your\kicad-project'
$Env:KICAD_MCP_PROFILE = 'pcb_only'
$Env:KICAD_MCP_OPERATING_MODE = 'readonly'
uvx kicad-mcp-pro --transport http --host 127.0.0.1 --port 3334
```

The default endpoint is:

```text
http://127.0.0.1:3334/mcp
```

The loopback examples above do not need `KICAD_MCP_AUTH_TOKEN`. Set
`KICAD_MCP_AUTH_TOKEN` only when HTTP binds outside loopback or crosses a tunnel or remote
network boundary. Clients must then send the same value as a bearer token. Store the token
in local environment or secret storage and never in a checked-in config example.

VS Code HTTP example:

```json
{
  "servers": {
    "kicad": {
      "type": "http",
      "url": "http://127.0.0.1:3334/mcp"
    }
  }
}
```

Codex HTTP example:

```toml
[mcp_servers.kicad]
url = "http://127.0.0.1:3334/mcp"
tool_timeout_sec = 120
```

Gemini CLI HTTP example:

```json
{
  "mcpServers": {
    "kicad": {
      "httpUrl": "http://127.0.0.1:3334/mcp",
      "timeout": 120000
    }
  }
}
```

## References

- Agent onboarding and examples: ../../../docs/agents/client-configs.md
- VS Code MCP configuration: https://code.vscode.dev/docs/copilot/customization/mcp-servers
- Codex MCP configuration: https://developers.openai.com/codex/config-reference
- Claude Code MCP configuration: https://docs.anthropic.com/en/docs/claude-code/mcp
- Anthropic MCP overview: https://docs.anthropic.com/en/docs/mcp
- Cursor MCP configuration: https://docs.cursor.com/en/context/mcp
- Gemini CLI MCP setup notes: https://github.com/google-gemini/gemini-cli/blob/main/docs/tools/mcp-server.md

# KiCad Studio

KiCad Studio lives in this monorepo under `apps/vscode-extension`. It should
discover and launch this server through the public CLI and MCP surfaces instead
of importing Python modules from `packages/mcp-server`.

## CLI Contract

```bash
uvx kicad-mcp-pro --help
uvx kicad-mcp-pro health --json
uvx kicad-mcp-pro doctor --json
uvx kicad-mcp-pro doctor --json --bundle ./mcp-debug.zip
uvx kicad-mcp-pro serve
```

`health --json` must succeed when the package is installed, even if KiCad is not
running. `doctor --json` may report degraded KiCad IPC status but should not
crash for normal diagnosable conditions. KiCad Studio may call the doctor
command directly for setup diagnostics; it does not start the MCP server.

Stable fields for extension consumption:

- `ok`
- `schemaVersion`
- `status`
- `package.name`
- `package.version`
- `python.version`
- `mcp.transport_default`
- `mcp.profile`
- `mcp.host`
- `mcp.port`
- `mcp.mount_path`
- `mcp.stateful_http`
- `kicad.cli_path`
- `kicad.cli_found`
- `kicad.version`
- `kicad.ipc_reachable`
- `config.workspace_root`
- `config.project_dir`
- `config.project_file`
- `config.pcb_file`
- `config.sch_file`
- `config.timeout_ms`
- `config.retries`
- `tools.tool_count`
- `tools.category_count`
- `tools.capability_summary`
- `live_context.available`
- `recent_errors[]`
- `checks[].name`
- `checks[].status`
- `checks[].message`
- `checks[].hint`

## Compatibility

| KiCad Studio | kicad-mcp-pro  | Notes                                                                                                                                      |
| ------------ | -------------- | ------------------------------------------------------------------------------------------------------------------------------------------ |
| 2.8.x        | >=3.5.2,<4.0.0 | Recommended HTTP bridge contract: local port `27185`, Streamable HTTP endpoint `/mcp`, optional legacy `/sse` only when explicitly enabled |

## Recommended HTTP Bridge Environment

```bash
KICAD_MCP_TRANSPORT=http
KICAD_MCP_HOST=127.0.0.1
KICAD_MCP_PORT=27185
KICAD_MCP_CORS_ORIGINS=vscode-webview://kicad-studio
KICAD_MCP_AUTH_TOKEN=replace-with-local-token
KICAD_MCP_STUDIO_WATCH_DIR=/absolute/path/to/projects
KICAD_MCP_WORKSPACE_ROOT=/absolute/path/to/projects
KICAD_MCP_PROFILE=full
```

`27185` is the recommended Studio bridge port for local setups. The server still defaults to `3334`, so set the port explicitly if you want this convention.

Run the bridge directly with the same flags emitted by KiCad Studio:

```bash
kicad-mcp-pro --transport http --port 27185
```

This starts the primary MCP endpoint at `http://127.0.0.1:27185/mcp`.
`/.well-known/mcp-server` reports the same endpoint for discovery. Legacy SSE
is intentionally disabled by default; clients that still require
`http://127.0.0.1:27185/sse` must start the server with
`KICAD_MCP_LEGACY_SSE=true` and enable their own legacy fallback setting.

## Integration Points

- `studio_push_context()` pushes active file, DRC errors, selected net/reference, and cursor state into the server.
- `kicad://studio/context` is the resource that agents can read directly.
- `KICAD_MCP_STUDIO_WATCH_DIR` watches for `.kicad_pro` updates and auto-selects the active project.
- `KICAD_MCP_WORKSPACE_ROOT` constrains project artifact reads and writes for safe extension-driven operation.
- The manufacturing release help link used by KiCad Studio is `https://oaslananka.github.io/kicad-mcp-pro/mcp/workflows/manufacturing-export/`; the canonical repository publishes that path through the docs workflow.

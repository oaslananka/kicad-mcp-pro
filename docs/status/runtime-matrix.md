# Runtime Matrix

This matrix describes the supported runtime surface for KiCad MCP Pro.

## Python

| Python | Status | Notes                                   |
| ------ | ------ | --------------------------------------- |
| 3.13   | Tested | Primary package and Docker runtime.     |
| 3.14   | Tested | Covered by CI for pure Python behavior. |

## Operating Systems

| Platform        | Status                      | Notes                                                                                                                            |
| --------------- | --------------------------- | -------------------------------------------------------------------------------------------------------------------------------- |
| Linux X64       | Tested                      | Primary CI platform via GitHub-hosted `ubuntu-24.04` in `oaslananka/kicad-mcp-pro`.                                           |
| Other platforms | Supported by package design | Local users may run the package elsewhere; release publishing uses GitHub-hosted runners where trusted publishing requires them. |

## KiCad Availability

| KiCad CLI | Status   | Behavior                                                                                                                        |
| --------- | -------- | ------------------------------------------------------------------------------------------------------------------------------- |
| Present   | Full     | CLI-backed exports, validation, and diagnostics can run.                                                                        |
| Missing   | Degraded | `health --json` and most metadata/config commands still work. IPC-dependent tools report unavailable state instead of crashing. |

## Transports

| Transport       | Status                                 | Invocation                                                                                                                                |
| --------------- | -------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------- |
| stdio           | Default for direct CLI installs        | `uvx kicad-mcp-pro` or `docker run --rm -i ghcr.io/oaslananka/kicad-mcp-pro:<version> --transport stdio`                                  |
| streamable-http | Default for the published Docker image | `docker run --rm -p 127.0.0.1:3334:3334 -e KICAD_MCP_AUTH_TOKEN=... ghcr.io/oaslananka/kicad-mcp-pro:<version>` |

HTTP mode should be bound only on trusted networks unless authentication,
network policy, and CORS are configured.

## MCP Clients

| Client         | Status    | Notes                                                                             |
| -------------- | --------- | --------------------------------------------------------------------------------- |
| Claude Desktop | Supported | Use stdio with `uvx kicad-mcp-pro`.                                               |
| Cursor         | Supported | Use stdio with absolute project paths when setting project environment variables. |
| VS Code MCP    | Supported | Use stdio with a `servers` configuration entry.                                   |
| Codex          | Supported | Use stdio configuration for local agent workflows.                                |
| Claude Code    | Supported | Use stdio configuration; see the integration guide.                               |

## Containers

The default container image does not bundle KiCad. It is suitable for stdio MCP
usage, metadata commands, and host-mounted or externally configured KiCad CLI
paths. Install KiCad on the host or use a dedicated CI image when full CLI export
coverage is required inside the container.

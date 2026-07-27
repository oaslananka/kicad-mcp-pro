# Configuration

Configuration is resolved in this order:

1. CLI arguments
2. Environment variables
3. `.env`
4. `~/.config/kicad-mcp-pro/config.toml`
5. Built-in defaults

The active project can also be changed at runtime with `kicad_set_project()`.

## Operating Modes

`KICAD_MCP_OPERATING_MODE` controls the risk level of the advertised and executable
tool surface. It is applied after the server profile, so a profile can narrow categories
while the operating mode still blocks unsafe calls.

| Mode | Tool surface |
| ---- | ------------ |
| `readonly` | Default. Project, schematic, PCB, DRC/ERC, BOM, netlist, and source-safe export inspection. |
| `write` | `readonly` plus controlled schematic and PCB source modifications and save operations. |
| `manufacturing` | `readonly` plus manufacturing package and handoff workflows. General schematic/PCB write tools stay hidden. |
| `experimental` | Full opt-in surface including write, manufacturing, routing, tuning, and unstable tools. |

Equivalent CLI usage:

```bash
kicad-mcp-pro --mode readonly
kicad-mcp-pro serve --mode write
kicad-mcp-pro tools list --mode manufacturing
```

The legacy `--experimental` flag remains accepted and maps to `--mode experimental`
when no explicit mode is supplied. `kicad_get_server_info` reports the active mode,
the default mode, and structured per-tool mode availability so clients can disable
features before invoking blocked tools.

## CLI Diagnostics

```bash
kicad-mcp-pro health --json
kicad-mcp-pro doctor --json
kicad-mcp-pro doctor --json --bundle ./mcp-debug.zip
kicad-mcp-pro version --json
```

`health --json` is a fast install/configuration check and does not require a
running KiCad IPC server. `doctor --json` adds deeper KiCad CLI and IPC probes
but reports unavailable KiCad as a degraded diagnostic state instead of printing
a stack trace. The doctor JSON is schema-validated before it is printed and
includes active project paths, transport host/port/mount settings, stateful HTTP
mode, tool and category counts, a capability summary, live GUI context
availability, and redacted recent diagnostic errors. `--bundle` writes a
redacted zip with `doctor.json`, the generated JSON schema, safe environment
metadata, and a README; it never includes plaintext tokens or credentials.

## Environment Aliases

Existing `KICAD_MCP_*` variables continue to work. The server also accepts these
interop aliases for launchers and editors:

| Alias                         | Internal field                        |
| ----------------------------- | ------------------------------------- |
| `KICAD_API_TOKEN`             | KiCad IPC token                       |
| `KICAD_API_SOCKET`            | KiCad IPC endpoint URI or socket path |
| `KICAD_CLI_PATH`              | `kicad-cli` path                      |
| `KICAD_MCP_TIMEOUT_MS`        | IPC timeout in milliseconds           |
| `KICAD_MCP_RETRIES`           | IPC connection retries                |
| `KICAD_MCP_HEADLESS`          | Headless preference                   |
| `KICAD_MCP_WORKSPACE_ROOT`    | Workspace root for path safety        |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | OpenTelemetry OTLP collector endpoint |
| `OTEL_EXPORTER_OTLP_HEADERS`  | OpenTelemetry OTLP exporter headers   |
| `OTEL_EXPORTER_OTLP_PROTOCOL` | `http/protobuf` or `grpc`             |
| `OTEL_SERVICE_NAME`           | OpenTelemetry service name            |

Diagnostics only report whether tokens are configured. Token values are never
printed.


## Schematic Grid Defaults

Schematic write tools keep snapping enabled by default and use a 1.27 mm / 50 mil grid. This matches common KiCad library symbols, including `Device:R`, whose pins may not land cleanly on a 2.54 mm / 100 mil grid when the symbol body is centered. Agents should prefer the default snapped behavior instead of disabling snap globally.

Set `KICAD_MCP_SCHEMATIC_GRID_MM` before server startup to override the schematic snap grid for a project or launcher:

```bash
KICAD_MCP_SCHEMATIC_GRID_MM=1.27
```

Invalid, zero, negative, or unreasonably large values fall back to the built-in 1.27 mm default. PCB placement grid defaults are independent and are not changed by this setting.

## KiCad IPC Capability Discovery

`kicad_get_server_info` reports the live IPC state that MCP clients use to gate
editing workflows. The contract includes the resolved IPC endpoint source,
KiCad IPC/API version, live PCB and schematic context flags, and a
`liveEditingTools` map for the OASLANA-119 tool names. When KiCad IPC is
unavailable, live editing tools are hidden from MCP tool discovery while
file-backed read, DRC, ERC, and export operations remain available when their
CLI/project prerequisites are satisfied.

For external KiCad plugin launchers, `KICAD_API_SOCKET` and `KICAD_API_TOKEN`
are accepted alongside the `KICAD_MCP_*` equivalents. Explicit IPC endpoints
may be NNG URIs such as `ipc:///tmp/kicad/api.sock`,
`ipc://C:\Users\Admin\AppData\Local\Temp\kicad\api.sock`, or
`tcp://127.0.0.1:4242`. URI values are passed to kipy unchanged; plain filesystem
paths continue to be expanded as socket paths. Leave the socket setting unset to
use kipy's platform-default discovery.

## Structured Logging

The server writes text logs to stderr by default. Use JSON Lines when logs need
to be parsed by an MCP client, CI collector, or operator tool:

```bash
kicad-mcp-pro --log-format json
kicad-mcp-pro serve --log-level warn --log-format json --log-file ./kicad-mcp-pro.log
```

`--log-format` accepts `text` or `json`; `console` remains a compatibility alias
for existing launchers. `--log-level` accepts `debug`, `info`, `warn`,
`warning`, `error`, and `critical`. The same controls are available as
`KICAD_MCP_LOG_LEVEL`, `KICAD_MCP_LOG_FORMAT`, and `KICAD_MCP_LOG_FILE`.
File logging rotates by size with bounded retention. Configure the default
5,000,000 byte limit and three retained backups through
`KICAD_MCP_LOG_MAX_BYTES` and `KICAD_MCP_LOG_BACKUP_COUNT`.

JSON log records always carry `ts`, `level`, `event`, `request_id`,
`mcp_session_id`, `tool`, `latency_ms`, and `error` fields. Tool calls emit
entry and exit events; Streamable HTTP logs initialize, session creation, and
session destruction lifecycle events. KiCad path fields, secret-like fields, and
oversized payload text are redacted before records reach stderr or rotated log
files. Structured errors include type and message by default; stack output is
limited to debug logging.

## OpenTelemetry

OpenTelemetry is disabled by default. It is enabled when
`OTEL_EXPORTER_OTLP_ENDPOINT` is set or when the server is started with
`--telemetry`:

```bash
OTEL_EXPORTER_OTLP_ENDPOINT=http://127.0.0.1:4318 kicad-mcp-pro --telemetry
```

The exporter supports OTLP/HTTP and OTLP/gRPC through
`OTEL_EXPORTER_OTLP_PROTOCOL`:

```bash
OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf
OTEL_EXPORTER_OTLP_PROTOCOL=grpc
```

Set `OTEL_EXPORTER_OTLP_HEADERS` for collector authentication and
`OTEL_SERVICE_NAME` to override the default `kicad-mcp-pro` service name. The
same opt-in switch is available as `KICAD_MCP_TELEMETRY_ENABLED=true` for
launchers that cannot pass CLI flags.

If telemetry is enabled without an explicit endpoint, the server uses local
collector defaults: `http://127.0.0.1:4318` for OTLP/HTTP and
`http://127.0.0.1:4317` for OTLP/gRPC. No third-party endpoint is enabled by
default. Set `KICAD_MCP_TELEMETRY_BUFFER_MAX_EVENTS` to control the bounded
redacted event buffer; the default is `100`, and `0` disables the buffer.

The server emits spans for MCP request handling, MCP tool calls, KiCad CLI
subprocess execution, and file-backed PCB parsing. It also emits these metrics:

| Metric                        | Labels              |
| ----------------------------- | ------------------- |
| `mcp_tool_invocations_total`  | `tool`, `status`    |
| `mcp_tool_duration_seconds`   | `tool`              |
| `mcp_session_active`          | none                |
| `kicad_cli_invocations_total` | `command`, `status` |
| `kicad_cli_duration_seconds`  | `command`           |

Telemetry attributes intentionally avoid project paths, board contents,
schematic contents, CLI output, request arguments, and collector headers.

## Workspace Safety

When `KICAD_MCP_WORKSPACE_ROOT` is set, project artifact reads and writes must
stay under that root. Without an explicit workspace root, the active project root
is used for normal project artifacts and the current working directory is the
fallback before a project is selected.

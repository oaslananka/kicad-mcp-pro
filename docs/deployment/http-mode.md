# HTTP Mode

The server can run in `streamable-http` mode in addition to `stdio`.

## Behavior

- MCP endpoint: `/mcp`
- Discovery endpoint: `/.well-known/mcp-server`
- Optional bearer-token auth
- Optional `/metrics` endpoint when `KICAD_MCP_ENABLE_METRICS=true`
- Optional OpenTelemetry OTLP export when `OTEL_EXPORTER_OTLP_ENDPOINT` is set or `--telemetry` is passed
- Optional CORS allowlist using explicit `http://`, `https://`, or `vscode-webview://` origins only
- Wildcard CORS (`*`) is rejected intentionally
- Stateless HTTP by default, with opt-in stateful HTTP for session-aware clients
- Legacy `/sse` and `/messages` routes stay disabled unless `KICAD_MCP_LEGACY_SSE=true`

The default HTTP port is `3334`. For KiCad Studio local bridge setups, `27185` is a good convention if you want a dedicated port.

Stateless mode is the ChatGPT-compatible default. In this mode the initialize
response does not include `Mcp-Session-Id`, and follow-up requests such as
`tools/list` must work without a session header. Set `KICAD_MCP_STATEFUL_HTTP=true`
only for clients that preserve `Mcp-Session-Id` from the initialize response and
send it on subsequent Streamable HTTP requests.

## Environment Variables

- `KICAD_MCP_TRANSPORT=http`
- `KICAD_MCP_HOST=127.0.0.1`
- `KICAD_MCP_PORT=3334`
- `KICAD_MCP_CORS_ORIGINS=https://app.example.com,http://127.0.0.1:3334`
- `KICAD_MCP_AUTH_TOKEN=...`
- `KICAD_MCP_HTTP_BOUNDARY=direct|loopback-proxy|tls-proxy` (default: `direct`)
- `KICAD_MCP_PUBLIC_BASE_URL=https://mcp.example.com` for `tls-proxy`, or a loopback HTTP origin for `loopback-proxy` container publishing
- `KICAD_MCP_TLS_CERT_FILE=/path/to/server.crt` and `KICAD_MCP_TLS_KEY_FILE=/path/to/server.key` for direct TLS termination
- `KICAD_MCP_STATEFUL_HTTP=true`
- `KICAD_MCP_ENABLE_METRICS=true`
- `KICAD_MCP_LEGACY_SSE=true`
- `OTEL_EXPORTER_OTLP_ENDPOINT=http://127.0.0.1:4318`
- `OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf`
- `OTEL_SERVICE_NAME=kicad-mcp-pro`

## Discovery, Metrics, and Token Rotation

- `GET /.well-known/mcp-server` returns the server card plus `capabilities.toolCategories`,
  `capabilities.profiles`, and `capabilities.experimentalTools` so clients can negotiate a
  profile before listing tools.
- `GET /metrics` emits in-memory Prometheus text metrics for tool calls and sliding-window
  p50/p95 latency when metrics are enabled.
- OpenTelemetry emits MCP request, tool, KiCad CLI, and PCB parser spans plus
  tool/session/CLI metrics to the configured OTLP collector. Attributes do not
  include project paths, board contents, schematic contents, request arguments,
  CLI output, or collector headers.
- `POST /.well-known/mcp-server/token-rotate` rotates the in-memory bearer token. The request
  must authenticate with the current token and send JSON like `{"new_token": "..."}`.

## Notes

- When bearer auth is enabled, cross-origin `POST /mcp` requests are checked against `KICAD_MCP_CORS_ORIGINS`.
- If you run over `stdio`, `KICAD_MCP_AUTH_TOKEN` is ignored and a startup warning is emitted.
- Use explicit origins instead of wildcard origins so the allowlist stays valid and auditable.
- A bearer token alone is not sufficient for a non-loopback HTTP bind. The server fails closed unless `KICAD_MCP_HTTP_BOUNDARY` explicitly selects direct TLS, a bind-all container published only to loopback, or a trusted TLS-terminating proxy/tunnel.
- `loopback-proxy` requires a bind-all server host plus a loopback HTTP `KICAD_MCP_PUBLIC_BASE_URL`. `tls-proxy` requires an HTTPS public base URL. The default `direct` boundary requires certificate/key TLS for non-loopback binds.
- When direct TLS is used, certificate and key files must both be configured. Bind-all direct TLS also requires `KICAD_MCP_PUBLIC_BASE_URL` so discovery never advertises `0.0.0.0`/`::`.
- Token rotation is intentionally in-memory; update your environment or TOML config separately for persistence.

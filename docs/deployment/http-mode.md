# HTTP Mode

The server can run in `streamable-http` mode in addition to `stdio`.

## Behavior

- MCP endpoint: `/mcp`
- Discovery endpoint: `/.well-known/mcp-server`
- Optional bearer-token auth
- Optional `/metrics` endpoint when `KICAD_MCP_ENABLE_METRICS=true`
- Optional CORS allowlist using explicit `http://`, `https://`, or `vscode-webview://` origins only
- Wildcard CORS (`*`) is rejected intentionally
- Stateless HTTP by default, with opt-in stateful HTTP for session-aware clients
- Legacy `/sse` and `/messages` routes stay disabled unless `KICAD_MCP_LEGACY_SSE=true`

The default HTTP port is `3334`. For KiCad Studio local bridge setups, `27185` is a good convention if you want a dedicated port.

## Environment Variables

- `KICAD_MCP_TRANSPORT=http`
- `KICAD_MCP_HOST=127.0.0.1`
- `KICAD_MCP_PORT=3334`
- `KICAD_MCP_CORS_ORIGINS=https://app.example.com,http://127.0.0.1:3334`
- `KICAD_MCP_AUTH_TOKEN=...`
- `KICAD_MCP_STATEFUL_HTTP=true`
- `KICAD_MCP_ENABLE_METRICS=true`
- `KICAD_MCP_LEGACY_SSE=true`

## Discovery, Metrics, and Token Rotation

- `GET /.well-known/mcp-server` returns the server card plus `capabilities.toolCategories`,
  `capabilities.profiles`, and `capabilities.experimentalTools` so clients can negotiate a
  profile before listing tools.
- `GET /metrics` emits in-memory Prometheus text metrics for tool calls and sliding-window
  p50/p95 latency when metrics are enabled.
- `POST /.well-known/mcp-server/token-rotate` rotates the in-memory bearer token. The request
  must authenticate with the current token and send JSON like `{"new_token": "..."}`.

## Notes

- When bearer auth is enabled, cross-origin `POST /mcp` requests are checked against `KICAD_MCP_CORS_ORIGINS`.
- If you run over `stdio`, `KICAD_MCP_AUTH_TOKEN` is ignored and a startup warning is emitted.
- Use explicit origins instead of wildcard origins so the allowlist stays valid and auditable.
- Token rotation is intentionally in-memory; update your environment or TOML config separately for persistence.

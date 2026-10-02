# MCP Transport

kicad-mcp-pro supports local MCP workflows through stdio and Streamable HTTP. The extension uses
the transport configured in its MCP profile and validates server-info before calling tools.

## Streamable HTTP

Use Streamable HTTP when a client needs a stable local endpoint, session handling, bearer-token
authentication, or integration with ChatGPT-style connectors.

```bash
uv run --project packages/mcp-server --all-extras kicad-mcp-pro --transport streamable-http --host 127.0.0.1 --port 3334
```

The default MCP path is `/mcp`. Set `KICAD_MCP_MOUNT_PATH` when a client or
reverse proxy requires a different endpoint such as `/custom-mcp`.

Clients must send each JSON-RPC request, response, or notification as a new
HTTP `POST` request to the configured endpoint. Every Streamable HTTP request
must include `Accept: application/json, text/event-stream` and JSON requests
must include `Content-Type: application/json`.

After `initialize`, clients must echo the negotiated protocol version in the
`MCP-Protocol-Version` header on follow-up requests. The public stable baseline
remains `2025-11-25`; the pinned MCP SDK also negotiates its supported earlier
protocol versions for backward-compatible clients such as Codex. Stateful
deployments also return `MCP-Session-Id` from
`initialize`; clients must echo that value on `notifications/initialized`,
`tools/list`, `tools/call`, and later requests. Missing stateful session IDs
return HTTP 400 with a structured JSON-RPC error, and unknown session IDs return
HTTP 404 with a structured JSON-RPC error.

The default local mode is stateless Streamable HTTP. This allows ChatGPT-style
connectors to initialize, send `notifications/initialized`, list tools, and call
tools without a session-header injection proxy. Set `KICAD_MCP_STATEFUL_HTTP=1`
only when the deployment needs server-side HTTP session tracking.

Deprecated HTTP+SSE routes are disabled by default. Set
`KICAD_MCP_LEGACY_SSE=1` only for old clients that cannot speak Streamable HTTP;
the compatibility routes are exposed alongside `/mcp` as `/sse` and
`/messages`.

Transport conformance coverage lives in
`packages/mcp-server/tests/unit/test_mcp_protocol_contract.py` and runs through:

```bash
corepack pnpm run test:contract
```

## stdio

Use stdio when the MCP client launches the server process directly and keeps it bound to the local
client session.

```bash
uv run --project packages/mcp-server --all-extras kicad-mcp-pro --transport stdio
```

## Compatibility

Protocol and capability expectations are generated in [MCP API reference](api-reference.md). Runtime
support boundaries are tracked in the [runtime matrix](../status/runtime-policy-matrix.md).

## MCP 2026 native SDK canary lane

> **Experimental:** The historical selector `2026-07-28-rc` now routes directly through the stable MCP Python SDK v2 final `2026-07-28` protocol implementation. It is not a general-availability protocol advertisement, and public registry metadata remains on MCP `2025-11-25`.

Start an isolated stateless Streamable HTTP canary with:

```bash
export KICAD_MCP_TRANSPORT=streamable-http
export KICAD_MCP_PROTOCOL_LANE=2026-07-28-rc
export KICAD_MCP_STATEFUL_HTTP=0
uv run --all-extras kicad-mcp-pro
```

The native SDK validates the final `MCP-Protocol-Version: 2026-07-28`, `Mcp-Method`, `Mcp-Name`, and required per-request `_meta` envelope. KiCad MCP Pro no longer rewrites requests into the stable handshake protocol or decorates responses through a compatibility bridge.

Call `server/discover` directly; `initialize` and `notifications/initialized` are not part of the final 2026 protocol. The lane is stateless: it neither requires nor emits `Mcp-Session-Id`, and an obsolete incoming session header does not establish server-side session state. Tasks and Apps are explicitly unsupported and unadvertised; server construction fails closed if a protocol extension is registered.

Reviewed repository cache policy is preserved through SDK-native cache hints: list methods use `300000` ms private caching, resource reads use `60000` ms private caching, and `server/discover` uses `3600000` ms private caching. `tools/list` remains alphabetically ordered in this canary lane.

Authentication is unchanged. When bearer [REDACTED] is configured, an unauthenticated request receives the existing authorization response before any protocol-specific diagnostic. Tool and resource visibility therefore remains scoped to the authenticated deployment, selected profile, operating mode, and live KiCad capabilities.

To roll back:

```bash
unset KICAD_MCP_PROTOCOL_LANE
# Restart the server, then use the normal MCP 2025-11-25 initialize flow.
```

After restart, the native SDK-v2 stable path negotiates `2025-11-25` through `initialize`, and public metadata remains `2025-11-25`. Native SDK v2 can still answer `server/discover`; that does not mean the opt-in modern-protocol canary is active.

The native canary and migration decision are recorded in [ADR-0006](../adr/0006-mcp-2026-stateless-compatibility-lane.md).

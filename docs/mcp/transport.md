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

## MCP 2026 native-v2 canary lane

> **Experimental:** This is an opt-in native SDK v2 canary for controlled final-protocol testing. It is not a general-availability protocol advertisement, and public registry metadata remains on MCP `2025-11-25`.

Start an isolated stateless Streamable HTTP canary with:

```bash
export KICAD_MCP_TRANSPORT=streamable-http
export KICAD_MCP_PROTOCOL_LANE=2026-07-28-rc
export KICAD_MCP_STATEFUL_HTTP=0
uv run --all-extras kicad-mcp-pro
```

The environment value keeps its historical `2026-07-28-rc` spelling so existing canary deployments remain reversible, but the temporary request/response translation bridge has been removed. Requests are handled directly by MCP Python SDK v2 using the final `2026-07-28` protocol.

Each final-protocol request requires `MCP-Protocol-Version: 2026-07-28` and `Mcp-Method`. `tools/call`, `prompts/get`, and `resources/read` also use `Mcp-Name` according to the final SDK contract. Every request carries the required protocol and client-capability values in `params._meta`; `io.modelcontextprotocol/clientInfo` remains useful for diagnostics and is not persisted.

The lane is stateless. KiCad MCP Pro continues to reject `Mcp-Session-Id` in this canary as a fail-closed transport guard. `server/discover`, list/call, resource/prompt operations, final-protocol validation, `resultType`, and server metadata are all produced by the native SDK v2 path.

KiCad MCP Pro preserves the reviewed cache policy through SDK v2 cache hints: `server/discover` is private for 3,600,000 ms; list methods are private for 300,000 ms; and `resources/read` is private for 60,000 ms. `tools/list` remains alphabetically ordered as an explicit repository contract.

Tasks and Apps extensions are not advertised. Authentication is unchanged: when bearer authentication is configured, authorization runs before protocol diagnostics.

To roll back:

```bash
unset KICAD_MCP_PROTOCOL_LANE
# Restart the server, then use the normal MCP 2025-11-25 initialize flow.
```

After restart, the native SDK-v2 stable path negotiates `2025-11-25` through `initialize`, and public metadata remains `2025-11-25`. Native SDK v2 can still answer `server/discover`; that does not mean the canary selector is active.

The migration and release decision are recorded in [ADR-0006](../adr/0006-mcp-2026-stateless-compatibility-lane.md).

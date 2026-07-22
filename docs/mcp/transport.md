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

After `initialize`, clients must include `MCP-Protocol-Version: 2025-11-25` on
follow-up requests. Stateful deployments also return `MCP-Session-Id` from
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

## MCP 2026 release-candidate compatibility lane

> **Experimental:** This is a release-candidate compatibility lane for controlled canary testing. It is not a general-availability protocol advertisement, and public registry metadata remains on MCP `2025-11-25`.

Start an isolated stateless Streamable HTTP canary with:

```bash
export KICAD_MCP_TRANSPORT=streamable-http
export KICAD_MCP_PROTOCOL_LANE=2026-07-28-rc
export KICAD_MCP_STATEFUL_HTTP=0
uv run --all-extras kicad-mcp-pro
```

The candidate lane requires `MCP-Protocol-Version: 2026-07-28` and `Mcp-Method` on every JSON-RPC POST. `tools/call`, `prompts/get`, and `resources/read` also require `Mcp-Name` matching `params.name` or `params.uri`. Every request must include these values in `params._meta`:

- `io.modelcontextprotocol/protocolVersion`
- `io.modelcontextprotocol/clientCapabilities`
- `io.modelcontextprotocol/clientInfo` is recommended for diagnostics but is not persisted

Call `server/discover` directly; do not send `initialize` or `notifications/initialized`. The lane is stateless and rejects `Mcp-Session-Id`. Tasks and Apps extensions are intentionally not advertised.

Authentication is unchanged. When bearer authentication is configured, an unauthenticated request receives the existing authorization response before any protocol-specific diagnostic. Tool and resource visibility therefore remains scoped to the authenticated deployment, selected profile, operating mode, and live KiCad capabilities.

To roll back:

```bash
unset KICAD_MCP_PROTOCOL_LANE
# Restart the server, then use the normal MCP 2025-11-25 initialize flow.
```

The compatibility lane and migration decision are recorded in [ADR-0006](../adr/0006-mcp-2026-stateless-compatibility-lane.md).

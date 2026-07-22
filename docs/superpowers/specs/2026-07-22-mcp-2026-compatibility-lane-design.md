# MCP 2026-07-28 Compatibility Lane Design

## Goal

Add an explicitly opt-in compatibility lane that exercises the MCP `2026-07-28` stateless request/response contract without changing the production default, dependency floor, or public registry advertisement from `2025-11-25`.

## Source baseline

The lane is based on the MCP draft repository at commit `73720340e7c42ddaf4b303b86e81663e9a2796d0` (2026-07-21). The committed fixtures record the source commit and intentionally cover only the subset implemented by KiCad MCP Pro: discovery, tools, prompts, resources, Streamable HTTP headers, protocol negotiation, caching metadata, and authorization boundaries.

## Scope and constraints

- `2025-11-25` remains the default and continues to use the installed stable MCP Python SDK.
- `2026-07-28` is selected only with `KICAD_MCP_PROTOCOL_LANE=2026-07-28-rc` or the equivalent config value.
- The candidate lane is Streamable HTTP only, always stateless, and rejects `MCP-Session-Id`.
- The candidate lane does not advertise Tasks or Apps extensions until their release-candidate SDK contracts are implemented and host-smoke-tested.
- `server.json` continues to advertise only `2025-11-25` until a separately reviewed release decision is satisfied.
- No production dependency is upgraded to MCP Python SDK v2 in this change.

## Architecture

### Protocol contract module

`src/kicad_mcp/protocol_compat.py` owns protocol-lane constants and pure functions. It validates candidate request headers and request `_meta`, builds `server/discover`, rewrites candidate requests into the stable SDK envelope where required, and decorates successful JSON-RPC results with candidate response metadata.

This module contains no ASGI, FastMCP, authentication, or KiCad domain logic. It is independently unit-testable and acts as the compatibility boundary while the upstream Python SDK v2 remains prerelease.

### Configuration gate

`KiCadMCPConfig.protocol_lane` accepts `stable` or `2026-07-28-rc`. The existing `stable` default is behaviorally unchanged. Validation rejects candidate mode with non-Streamable-HTTP transports, `stateful_http=true`, legacy SSE, or the legacy experimental Tasks implementation.

### Streamable HTTP bridge

`_StreamableHttpContractMiddleware` branches only when the candidate lane is selected:

1. Preserve the existing bearer-token authorization boundary before protocol parsing.
2. Require `MCP-Protocol-Version: 2026-07-28`, `Mcp-Method`, and `Mcp-Name` for named operations.
3. Require per-request `_meta` protocol version and client capabilities; reject header/body or method/header mismatches with candidate error codes.
4. Handle `server/discover` directly.
5. Reject legacy initialization, session headers, and unsupported candidate methods.
6. Translate supported candidate requests to the installed stable SDK contract.
7. Decorate JSON responses with `resultType`, server identity metadata, and cache metadata where the candidate schema requires them.

The bridge never weakens authentication or exposes a session cache. Stable requests continue through the existing code path unchanged.

### Contract fixtures and CI lane

Focused fixtures under `tests/contracts/mcp/2026-07-28/` capture representative request and response envelopes plus provenance. `tests/unit/test_mcp_protocol_2026_contract.py` validates both fixture shape and live ASGI behavior. A separate CI job runs the candidate tests independently from the stable MCP contract suite and contributes to the required PR gate.

### Documentation and release decision

An ADR records component-level state assumptions and the migration boundary for transport, Tasks, Apps, authorization, caching, telemetry, benchmarks, and registry metadata. The release decision requires all of the following before `server.json` changes:

- the MCP `2026-07-28` specification is final,
- a stable MCP Python SDK supports the required surface,
- representative supported hosts pass smoke tests,
- Tasks/Apps extension advertisement matches implemented behavior,
- rollback to `2025-11-25` is documented and tested.

## Error handling

Candidate validation returns JSON-RPC errors with the request ID when available. Header mismatch uses `-32020`, missing required client capability uses `-32021`, and unsupported protocol version uses `-32022`. Malformed JSON remains a JSON-RPC parse error. Authentication failures retain the existing 401/403 response shape and are never converted into protocol diagnostics.

## Security and privacy

`tools/list`, prompts, and discovery are marked private when their visibility depends on authentication, profile, operating mode, or live KiCad state. Resource reads are always private. No authorization token, client metadata, or project content is persisted by the bridge. Public cache scope is used only for invariant unauthenticated discovery data.

## Testing

- Stable contract tests prove no behavior drift for `2025-11-25`.
- Candidate config tests prove fail-closed combinations.
- Pure contract tests cover metadata, headers, method/name matching, discovery, response decoration, and error codes.
- ASGI tests cover authenticated and unauthenticated candidate requests, direct tool discovery without initialization, rejected sessions, and cache metadata.
- Metadata tests prove `server.json` still advertises only `2025-11-25`.
- CI runs stable and candidate suites independently.

## Out of scope

- Replacing the stable Python SDK with MCP v2 prereleases.
- Implementing `subscriptions/listen`, MRTR, or the redesigned Tasks extension.
- Advertising MCP Apps or Tasks extensions in candidate discovery.
- Changing tool schemas solely to adopt new JSON Schema 2020-12 keywords.
- Changing the public registry protocol version before the release-decision gates pass.

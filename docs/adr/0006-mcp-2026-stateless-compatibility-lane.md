# ADR-0006: MCP 2026 Stateless Compatibility Lane

**Status:** Accepted
**Date:** 2026-07-22
**Deciders:** @oaslananka

## Context

The public server and registry metadata currently target MCP `2025-11-25` through the stable MCP Python SDK. The MCP `2026-07-28` release candidate removes protocol sessions and the initialize lifecycle, introduces mandatory per-request metadata and transport headers, requires `server/discover`, adds cache metadata, and moves Tasks back behind an extension boundary.

Adopting the draft globally before the specification, SDK, and supported hosts are stable would make the public contract misleading and could break existing clients. Ignoring the candidate until final release would leave transport, authorization, and response-shape risks untested.

## Decision

Maintain `2025-11-25` as the production default and public registry contract. Add an explicitly opt-in `2026-07-28-rc` compatibility lane at the Streamable HTTP boundary.

The candidate lane:

- is selected only with `KICAD_MCP_PROTOCOL_LANE=2026-07-28-rc`,
- requires stateless Streamable HTTP,
- rejects `Mcp-Session-Id`, `initialize`, and `notifications/initialized`,
- validates `MCP-Protocol-Version`, `Mcp-Method`, `Mcp-Name`, and required request `_meta`,
- serves `server/discover` directly,
- adapts supported requests to the installed stable SDK internally,
- adds candidate `resultType`, server metadata, and cache metadata to successful responses,
- advertises no Tasks or Apps extension until those contracts are implemented,
- does not change `server.json` or the stable dependency range.

The draft fixtures are pinned to modelcontextprotocol/modelcontextprotocol commit `73720340e7c42ddaf4b303b86e81663e9a2796d0`.

## Component state inventory

| Component | Existing state assumption | Candidate-lane decision |
| --- | --- | --- |
| Streamable HTTP | Optional process-local session tracking after initialize | Candidate requests are independent, include protocol/client metadata on every call, and never create a session |
| Tasks | Legacy experimental SDK Tasks handlers | Disabled and not advertised; the redesigned Tasks extension requires separate implementation |
| Apps | Host-specific Apps/UI integrations can depend on negotiated host behavior | Not advertised as a candidate extension until supported-host contract tests pass |
| Authorization | Bearer authentication is enforced by the existing FastMCP auth layer | Authentication remains before protocol diagnostics; candidate metadata never bypasses authorization |
| Caching | Clients receive no explicit MCP cache policy | Candidate list/read results receive bounded `ttlMs` and private `cacheScope` where visibility or content is authorization-dependent |
| Telemetry and benchmarks | Request telemetry can associate lifecycle/session fields | Candidate telemetry records protocol method without persisting client metadata or session state; benchmark fixtures remain sanitized |
| Registry metadata | `server.json` advertises stable protocol support | Registry metadata remains `2025-11-25` until the release gates below pass |

## Release decision gates

`server.json` may advertise `2026-07-28` only after all of these are true:

1. The final MCP 2026-07-28 specification is published and the pinned fixtures are reconciled.
2. A stable MCP Python SDK supports the required transport and schema surface without the compatibility bridge.
3. supported host smoke tests pass for direct discovery, listing, calling, authorization, and error behavior.
4. Tasks and Apps extension parity is implemented or explicitly excluded from advertised capabilities.
5. A tested rollback to the `2025-11-25` runtime and metadata contract is documented and verified.

Changing public metadata is a separate reviewed release decision, not an automatic consequence of this ADR.

## Rollout

1. Enable the lane only in an isolated canary deployment.
2. Run the independent MCP 2026 contract job and representative host smoke tests.
3. Compare authorization failures, tool visibility, latency, and response size with the stable lane.
4. Expand canary traffic only after no destructive-call or data-isolation regression is observed.
5. Keep stable clients and production registry traffic on `2025-11-25` throughout the evaluation.

## Rollback

Unset `KICAD_MCP_PROTOCOL_LANE`, restart the server, and verify `server/discover` is no longer accepted while the normal `initialize` flow negotiates `2025-11-25`. No data migration is required because the candidate bridge persists no protocol session or client metadata.

## Consequences

The repository gains early, deterministic evidence for the candidate protocol without introducing a prerelease production dependency. The temporary bridge adds maintenance cost and must be removed when a stable SDK natively implements the final contract. Candidate support is intentionally narrower than the full draft and must not be described as general availability.

## Verification

- `uv run pytest tests/unit/test_mcp_2026_config.py tests/unit/test_protocol_compat.py tests/unit/test_mcp_protocol_2026_contract.py -q`
- `uv run pytest tests/unit/test_mcp_protocol_contract.py tests/unit/test_mcp_manifest.py -q`
- `uv run pytest tests/integration/test_mcp_2026_host_smoke.py -q` runs loopback HTTP request-profile smoke cases for ChatGPT Connector and VS Code MCP clients. These cases verify wire behavior but do not claim certification of external host binaries.
- The CI job named `MCP 2026 Compatibility` passes independently.
- `server.json` continues to advertise only `2025-11-25`.

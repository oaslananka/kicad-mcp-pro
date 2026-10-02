# ADR-0006: MCP 2026 Stateless Compatibility Lane

**Status:** Accepted
**Date:** 2026-07-22
**Deciders:** @oaslananka

## Context

The public server and registry metadata remain on MCP `2025-11-25`. The repository now runs on stable MCP Python SDK v2, which natively implements the final `2026-07-28` stateless protocol surface, including per-request metadata, final request validation, `server/discover`, result metadata, and cache hints.

Before SDK v2 was adopted, KiCad MCP Pro carried an opt-in translation bridge behind `KICAD_MCP_PROTOCOL_LANE=2026-07-28-rc`. That bridge validated final-protocol requests, translated supported operations onto the older runtime, and decorated responses. It was intentionally temporary and must not survive once the native SDK provides equivalent or stronger behavior.

The old environment value remains useful as a reversible canary selector, but it no longer justifies a second protocol implementation.

## Decision

Maintain `2025-11-25` as the production default and public registry contract until a separate public-metadata review is approved.

Retain `KICAD_MCP_PROTOCOL_LANE=2026-07-28-rc` only as an opt-in stateless canary selector for the final `2026-07-28` protocol. The historical name is preserved for deployment compatibility. The temporary request/response translation bridge is removed; canary traffic is handled directly by MCP Python SDK v2.

The native canary:

- requires stateless Streamable HTTP;
- rejects `Mcp-Session-Id` as a repository fail-closed transport policy;
- relies on SDK v2 for final `MCP-Protocol-Version`, `Mcp-Method`, `Mcp-Name`, request `_meta`, `server/discover`, result-shape, and protocol-error behavior;
- keeps bearer authorization ahead of protocol diagnostics;
- preserves reviewed private cache hints with SDK v2 primitives;
- preserves alphabetical `tools/list` ordering as an explicit KiCad MCP Pro contract;
- advertises no Tasks or Apps extension;
- does not change `server.json` or public compatibility metadata.

The final-protocol fixtures remain pinned to modelcontextprotocol/modelcontextprotocol release commit `5f5440bb26a62e2cf3440b92da5a667efa03b267`.

## Component state inventory

| Component | Current decision |
| --- | --- |
| Streamable HTTP | The native SDK v2 handles final `2026-07-28` stateless requests directly. The canary selector requires stateless HTTP and rejects session headers. |
| Tasks | The obsolete SDK-v1 draft implementation is removed. `enable_tasks=true` fails closed and no Tasks extension is advertised. |
| Apps | No Apps extension is advertised. An explicit release-gate decision remains separate. |
| Authorization | Bearer authentication remains enforced before final-protocol diagnostics. |
| Caching | Native SDK v2 cache hints preserve private TTLs: 3,600,000 ms for discovery, 300,000 ms for list methods, and 60,000 ms for resource reads. |
| Telemetry and benchmarks | Native requests keep method-level telemetry without persisting client metadata or protocol sessions. |
| Registry metadata | `server.json` remains on `2025-11-25` pending a separate reviewed release decision. |

## Release decision gates

`server.json` may advertise `2026-07-28` only after all of these are true:

1. The final MCP 2026-07-28 specification is published and the pinned fixtures are reconciled.
2. A stable MCP Python SDK supports the required transport and schema surface without the compatibility bridge.
3. Supported host smoke tests pass for direct discovery, listing, calling, authorization, and error behavior.
4. Tasks and Apps extension parity is implemented or explicitly excluded from advertised capabilities.
5. A tested rollback to the `2025-11-25` runtime and metadata contract is documented and verified.

Changing public metadata is a separate reviewed release decision, not an automatic consequence of this ADR.

### Gate status (reviewed 2026-10-02)

| Gate | Status | Evidence |
| --- | --- | --- |
| 1. The final MCP 2026-07-28 specification is published and the pinned fixtures are reconciled. | **Complete.** Final fixtures under `tests/contracts/mcp/2026-07-28/` are pinned to release commit `5f5440bb26a62e2cf3440b92da5a667efa03b267`, including reviewed discovery/list/schema provenance. | Complete |
| 2. A stable MCP Python SDK supports the required transport and schema surface without the compatibility bridge. | **Complete.** The repository uses `mcp[cli]>=2.2.0,<3.0.0` with locked SDK v2.2.0. Final `2026-07-28` traffic is now handled directly by SDK v2. The temporary translation/decorating bridge has been removed. Repository-specific cache TTLs, alphabetical tool ordering, and the stateless session-header guard are retained using native SDK and transport primitives. | Complete |
| 3. Supported host smoke tests pass for direct discovery, listing, calling, authorization, and error behavior. | **Complete.** PR #1032 established native SDK-v2 real-HTTP request-profile evidence for ChatGPT Connector and VS Code MCP, covering discovery, listing, representative calls, bearer authorization, structured errors, and stateless no-session traffic. This is wire/request-profile evidence, not certification of external host binaries. | Complete |
| 4. Tasks and Apps extension parity is implemented or explicitly excluded from advertised capabilities. | **Partially complete.** Tasks are explicitly excluded/fail-closed: the SDK-v1 experimental draft implementation was removed and `enable_tasks=true` fails closed. Apps is not advertised, but its explicit reviewed release-gate decision remains open. | Tasks complete; Apps open |
| 5. A tested rollback to the `2025-11-25` runtime and metadata contract is documented and verified. | **Complete.** The rollback contract verifies the canary selector, final-protocol rejection of legacy `initialize`, removal of the selector, config reset/restart semantics, native SDK-v2 negotiation of `2025-11-25`, and unchanged public metadata. Native SDK v2 may continue to answer `server/discover` after rollback because discovery is part of the SDK's modern native surface. | Complete |

Gates 1–3 and 5 are complete. Gate 2 now includes removal of the temporary RC translation bridge. The explicit Apps extension-capability decision remains the final ADR gate before any separate public `2026-07-28` metadata change is considered.

## Rollout

1. Use the historical `2026-07-28-rc` selector only in isolated canary deployments.
2. Run the independent MCP 2026 compatibility job and maintained host-profile smoke tests.
3. Compare authorization failures, tool visibility, latency, cache behavior, and response size with the stable production path.
4. Keep public registry traffic on `2025-11-25` until a separate release decision changes it.

## Rollback

Unset `KICAD_MCP_PROTOCOL_LANE` and restart the server. Verify that the runtime returns to the stable SDK-v2 path: normal `initialize` negotiates `2025-11-25`, while public discovery metadata remains `2025-11-25`. Native SDK v2 may continue to answer `server/discover` after rollback; that is native SDK behavior and is not evidence that the canary selector is active.

No data migration is required because the canary path persists no protocol session or client metadata.

## Consequences

There is one native SDK-v2 protocol implementation instead of a repository-maintained translation layer. Repository policy is limited to behavior that belongs to KiCad MCP Pro: fail-closed stateless selection, bounded private cache hints, alphabetical tool discovery, authorization boundaries, and release gating.

The historical selector name remains temporarily for deployment compatibility, but it does not imply prerelease protocol semantics. Public `2026-07-28` advertisement remains separately gated.

## Verification

- `uv run pytest tests/unit/test_mcp_2026_config.py tests/unit/test_mcp_native_v2_bridge_disposition.py tests/unit/test_mcp_protocol_2026_contract.py -q`
- `uv run pytest tests/unit/test_mcp_protocol_contract.py tests/unit/test_mcp_manifest.py -q`
- `uv run pytest tests/integration/test_mcp_2026_host_smoke.py tests/integration/test_mcp_native_v2_protocol.py -q`
- The CI job named `MCP 2026 Compatibility` passes independently.
- `server.json` continues to advertise only `2025-11-25`.

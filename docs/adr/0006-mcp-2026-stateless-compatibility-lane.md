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
- advertises no Tasks or Apps extension; unsupported extension registration fails closed until separately implemented and reviewed,
- does not change `server.json` or the stable dependency range.

The compatibility fixtures are pinned to the final `2026-07-28` release of modelcontextprotocol/modelcontextprotocol at commit `5f5440bb26a62e2cf3440b92da5a667efa03b267`. `tests/contracts/mcp/2026-07-28/provenance.json` also records the reviewed source-document and schema blob identities.

## Component state inventory

| Component | Existing state assumption | Candidate-lane decision |
| --- | --- | --- |
| Streamable HTTP | Optional process-local session tracking after initialize | Candidate requests are independent, include protocol/client metadata on every call, and never create a session |
| Tasks | Legacy experimental SDK Tasks handlers | Disabled and not advertised; the redesigned Tasks extension requires separate implementation |
| Apps | Stable SDK v2.2.0 includes the opt-in `io.modelcontextprotocol/ui` Apps extension | Explicitly excluded and unadvertised: KiCad MCP Pro registers no `ui://` resources or UI-bound tools and rejects protocol-extension registration at server construction |
| Authorization | Bearer authentication is enforced by the MCPServer auth layer | Authentication remains before protocol diagnostics; candidate metadata never bypasses authorization |
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

### Gate status (reviewed 2026-10-02)

| Gate | Status | Evidence |
| --- | --- | --- |
| 1. The final MCP 2026-07-28 specification is published and the pinned fixtures are reconciled. | **Complete.** The Model Context Protocol project published `2026-07-28` as the final, authoritative successor to `2025-11-25` on 2026-07-28 ([spec announcement](https://blog.modelcontextprotocol.io/posts/2026-07-28/)). The contract fixtures under `tests/contracts/mcp/2026-07-28/` were reconciled against the immutable final release commit `5f5440bb26a62e2cf3440b92da5a667efa03b267`; `provenance.json` now pins that commit plus the reviewed `server/discover`, `tools/list`, and schema blob identities. The representative envelopes remain valid against the final source: per-request protocol/capability metadata, `server/discover` result metadata, `resultType`, and cache fields match the final contract. | Complete |
| 2. A stable MCP Python SDK supports the required transport and schema surface without the compatibility bridge. | **Complete; bridge removed.** The repository uses stable MCP Python SDK v2 (`mcp>=2.2.0,<3.0.0`). Final `2026-07-28` discovery, validation, stateless HTTP, result shaping, and server metadata now flow directly through SDK v2. The repository preserves its reviewed cache TTL/scope policy through SDK-native `cache_hints` and preserves alphabetical `tools/list` ordering in the opt-in modern lane. The former request/response translation module and interception path are removed. | Complete |
| 3. Supported host smoke tests pass for direct discovery, listing, calling, authorization, and error behavior. | **Complete.** PR #1032 (`test(mcp): refresh final-runtime host smoke`) merged native SDK-v2 real-HTTP request-profile smoke coverage for ChatGPT Connector and VS Code MCP. The tests cover direct discovery, listing, representative tool calls, bearer authorization, structured error behavior, and stateless no-session traffic. This is wire/request-profile evidence, not certification of external host binaries. | Complete |
| 4. Tasks and Apps extension parity is implemented or explicitly excluded from advertised capabilities. | **Complete.** Tasks remain explicitly excluded/fail-closed: the SDK-v1 draft implementation is removed and `enable_tasks=true` is rejected. Apps was evaluated against pinned MCP Python SDK v2.2.0 (`9972c21aa42054fb1450c5fc614761ed11847ec6`), whose built-in `Apps` extension advertises `io.modelcontextprotocol/ui` only when passed through `MCPServer(extensions=[...])`. KiCad MCP Pro has no `ui://` resources or UI-bound tools, so advertising Apps would overstate runtime support. `KiCadFastMCP` now rejects any protocol-extension registration and constructs the SDK server with an empty extension set; `server/discover` contract tests continue to require no `extensions` capability. | Tasks: explicitly excluded/fail-closed. Apps: explicitly excluded/fail-closed. |
| 5. A tested rollback to the `2025-11-25` runtime and metadata contract is documented and verified. | **Complete for the post-SDK-v2 runtime.** `test_candidate_lane_rollback_restores_native_stable_runtime_and_metadata` explicitly enables the temporary RC lane, verifies that it rejects legacy `initialize`, unsets `KICAD_MCP_PROTOCOL_LANE`, resets configuration to model a restart, and then verifies the native stable path negotiates `2025-11-25` through `initialize` while `/.well-known/mcp-server` continues to advertise `2025-11-25`. The same contract records the post-v2 semantic change: native SDK v2 may continue to answer `server/discover` after rollback because discovery is no longer unique to the temporary bridge. | Complete |

All five release decision gates are complete. This satisfies the technical compatibility prerequisites only; public `2026-07-28` metadata remains a separate reviewed release decision and is not authorized automatically.

## Compatibility-bridge disposition (2026-10-02)

The temporary compatibility bridge has been retired. The historical environment value `KICAD_MCP_PROTOCOL_LANE=2026-07-28-rc` remains as an opt-in canary selector so existing operator automation does not break, but requests are no longer translated to `2025-11-25` or decorated after the fact.

Native SDK v2 is now authoritative for final MCP `2026-07-28` request validation, `server/discover`, structured protocol errors, stateless transport behavior, result metadata, and server information. Two repository-specific behaviors are preserved explicitly at native seams:

- SDK-native `cache_hints` preserve `300000` ms private TTLs for list methods, `60000` ms private TTL for `resources/read`, and `3600000` ms private TTL for `server/discover`;
- `KiCadFastMCP.list_tools()` preserves alphabetical ordering only for the opt-in modern-protocol lane.

The final SDK does not turn an obsolete incoming `Mcp-Session-Id` header into session state in stateless mode, but it also does not reproduce the bridge's custom rejection response. That bridge-specific diagnostic is intentionally retired in favor of SDK-native final-protocol behavior. Authentication still precedes protocol diagnostics, and no session identifier is emitted.

At bridge-removal time, public registry/server metadata remained `2025-11-25`; bridge removal itself was not public protocol promotion.

## Extension-capability disposition (2026-10-02)

Tasks and Apps are both explicitly excluded from advertised capabilities for the current KiCad MCP Pro runtime. Tasks retain the existing fail-closed configuration guard. Apps was evaluated against MCP Python SDK v2.2.0, which ships `mcp.server.apps.Apps` as an opt-in extension with identifier `io.modelcontextprotocol/ui`. No `ui://` resources or UI-bound tools are registered in this repository, so there is no truthful Apps capability to advertise.

`KiCadFastMCP` therefore rejects non-empty protocol-extension registration at construction and passes an explicit empty extension set to the SDK. This converts accidental absence into a repository-owned fail-closed invariant. The modern discovery contract also asserts that `capabilities.extensions` is absent. Adding Tasks, Apps, or another MCP extension later requires a separate implementation tranche with runtime behavior, host negotiation evidence, and reviewed capability advertisement.

Gate 4 disposition: Tasks: explicitly excluded/fail-closed. Apps: explicitly excluded/fail-closed.

## Public protocol promotion (2026-10-02)

After all five release decision gates were complete, the public canonical MCP contract was promoted to final `2026-07-28` in a separate release change. The promotion deliberately separates the public canonical version from legacy initialize-based compatibility:

- `MCP_PROTOCOL_VERSION` and `compatibility.yaml.mcp.protocolVersion` identify the public canonical `2026-07-28` contract;
- `MCP_LEGACY_PROTOCOL_VERSION` remains `2025-11-25` for backward-compatible initialize/session clients and internal compatibility paths;
- `compatibility.yaml.mcp.supportedProtocolVersions` and generated `server.json` advertise `2026-07-28` first and retain `2025-11-25`;
- the local bridge deliberately uses the legacy wire version until it is separately migrated to final-protocol request envelopes;
- the historical `KICAD_MCP_PROTOCOL_LANE=2026-07-28-rc` selector remains as a strict stateless conformance mode rather than a prerequisite for final-protocol support.

This promotion does not enable Tasks or Apps. Both remain explicitly excluded and fail closed.

## Rollout

1. Enable the lane only in an isolated canary deployment.
2. Run the independent MCP 2026 contract job and representative host smoke tests.
3. Compare authorization failures, tool visibility, latency, and response size with the stable lane.
4. Expand canary traffic only after no destructive-call or data-isolation regression is observed.
5. Keep existing clients on `2025-11-25` throughout the evaluation; promote public metadata only in a separate reviewed change after all gates pass.

## Rollback

Unset `KICAD_MCP_PROTOCOL_LANE` and restart the server. Verify that the runtime returns to the native SDK-v2 stable path: the normal `initialize` flow negotiates `2025-11-25`, and public discovery metadata continues to advertise `2025-11-25`. Native SDK v2 may continue to answer `server/discover` after rollback; that method is now part of the SDK's native modern-protocol surface and is no longer evidence that the temporary RC bridge is active. No data migration is required because the candidate bridge persists no protocol session or client metadata.

## Consequences

The repository retains deterministic conformance evidence for the final protocol without a custom translation layer. Stable SDK v2 is the protocol authority; repository-owned behavior is limited to explicit cache policy, tool ordering, authentication, visibility, extension exclusion, and transport-security controls.

## Verification

- `uv run pytest tests/unit/test_mcp_2026_config.py tests/unit/test_native_2026_bridge_disposition.py tests/unit/test_mcp_protocol_2026_contract.py -q`
- `uv run pytest tests/unit/test_mcp_protocol_contract.py tests/unit/test_mcp_manifest.py -q`
- `uv run pytest tests/integration/test_mcp_2026_host_smoke.py -q` runs loopback HTTP request-profile smoke cases for ChatGPT Connector and VS Code MCP clients. These cases verify wire behavior but do not claim certification of external host binaries.
- The CI job named `MCP 2026 Compatibility` passes independently.
- `server.json` advertises `2026-07-28` as primary and retains `2025-11-25` in the supported-version list.

# Isolated MCP Tasks read-only ERC/DRC protocol probe (#1221)

**Status: hermetic test model, not a production feature, not a verified host.** No
changes are made to `kicad_mcp`, its tool registry, `server/discover`,
deployment, authentication, or any KiCad process. This only models the **draft
2026-07-28 Tasks extension** `io.modelcontextprotocol/tasks`, not the retired
legacy Tasks implementation. No write, PCB mutation, manufacturing, job queue,
network, background worker, real ERC/DRC, provider request or secret is involved.

## Reproduction and pinned compatibility boundary

- Fixture: `tests/research/mcp_tasks_fixture.py`
- Tests: `tests/unit/test_mcp_tasks_draft_fixture.py`
- Run: `uv run --offline --frozen --all-extras pytest -q tests/unit/test_mcp_tasks_draft_fixture.py`
- MCP SDK: `mcp==2.2.0` exactly pinned by `uv.lock`. The compatibility probe
  verifies this pinned SDK accepts the ordinary synchronous `tools/call`
  request and `CallToolResult` when Tasks capability is absent. **The pinned
  Python SDK does not yet implement this Tasks extension**; the draft
  `tasks/get`, `tasks/update`, `tasks/cancel` shapes are validated by the
  isolated JSON-RPC fixture itself. This does not claim interoperability with
  any real client/agent host.
- Contract source: [Official draft, 2026-07-28](
  https://tasks.extensions.modelcontextprotocol.io/specification/draft/tasks)
  and [SEP-2663](https://tasks.extensions.modelcontextprotocol.io/seps/2663-tasks-extension).
  Distinguish the final base MCP 2026-07-28 wire protocol from the separately
  evolving Tasks extension.

## Model boundaries

The fixture allows exactly two **synthetic** names:
`synthetic_erc_review` and `synthetic_drc_review`. The only accepted argument
is an optional boolean `requireInput` used to simulate a benign MRTR
acknowledgement or `simulateError` to test a regular tool-level
`isError: true` result that stays in the `completed` status. Any project data, command, path, write tool, or additional
argument is rejected. Results are hardcoded and explicitly say *zero real
designs analyzed*. Synthetic progress occurs **only** when test code calls
`advance`; read-only polling never executes work.

The extension is negotiated in each request through
`params._meta["io.modelcontextprotocol/clientCapabilities"].extensions`.
No extension, invalid extension or legacy-only hint yields an ordinary
`resultType: "complete"` for the synthetic tool. Task methods require the
capability on every request and otherwise return JSON-RPC `-32021`.
`tasks/list`, `tasks/result`, `tasks/create` and all other methods are
unimplemented (`-32601`). Creation returns flat
`resultType: "task"` / `taskId` metadata; GET returns complete, status-specific
results. CANCEL and UPDATE return ack-only complete responses.

Authentication is **not** implemented; a caller identity is injected into the
fixture *out of band* via the trusted test harness, modelling a properly
authenticated transport. In production, session identity must come from
verified credentials, never from client-provided task params. Tasks use opaque
192-bit-random handles and enforce exact owner equality. Unknown, expired,
restarted or cross-caller handles are indistinguishable (`-32602`), so no
task IDs or metadata are leaked. Restart invalidates all handles because the
fixture is memory-only; **that is intentionally not a durable production Tasks
backend**, whose creation must guarantee availability after disconnection.

## Limits, terminal behavior and security review

| Guard | Bound / behavior |
|---|---|
| Global retained records | 8 (allocation fails closed when full) |
| Inbound JSON message | 4096 bytes maximum |
| Identity length | 1–128 characters supplied by trusted transport |
| Synthetic deadline | 15 s, terminal `failed` with JSON-RPC error `-32603` |
| TTL | 60,000 ms, expired handles purged on access/create |
| Suggested poll | 1,000 ms; reads idempotent and O(1) per handle |
| Progress | Explicit synchronous fixture `advance` only, no CPU worker |
| Cancellation | Cooperative-model immediate `cancelled`, ack-only and idempotent |
| MRTR inputs | At most 8 response keys; unknown/duplicate keys ignored |
| Payloads | Fixed synthetic output only, no private paths, raw logs or credentials |

No network, filesystem, KiCad CLI, real job, provider, or benchmark operation
is performed. The failure/status tests cover deadline, timeout, cancellation,
invalid and cross-owner handles, restart, duplicate polls and update keys,
capacity, malformed messages, and clients lacking the extension. In a
production implementation, address durable storage encryption, access
revocation, per-caller quotas, concurrent state transitions, atomic writes,
resource scheduling, process cancellation, safe observability/redaction,
flood-control and host negotiation before publishing any capability.

**Decision:** This research fixture meets only the bounded protocol modelling
scope. No production Tasks support, compatibility badge, unattended execution
or release is authorized. Any real-world Tasks implementation requires a
separate opt-in security/design review, supported SDK/client runtime, and
protected PR with proven cross-platform behavior.

# MCP Apps and Tasks — isolated research gates (October 2026)

**Status: experimental research only — not enabled in production, not
advertised in the KiCad MCP capability negotiation.** The existing native MCP
`2026-07-28` implementation advertises neither Tasks nor Apps; tests must
continue to reject their unsupported registration.

## MCP Apps (portable, read-only UI proof)

Current ChatGPT-facing widgets are read-only and deployed on a separate
HTTPS/credential boundary. Before reusing one with the stable MCP Apps extension
(2026-01-26), build an **isolated** experiment using one of the existing
read-only summary views and `_meta.ui.resourceUri` / `ui://` resource metadata.
The UI should initialize via the portable `ui/initialize` bridge, receive
`ui/notifications/tool-result`, render the structured server summary, and
operate in a sandboxed iframe with restrictive content-security policy.
Do not migrate or overwrite the live ChatGPT Apps integration just for parity.

*Acceptance:* a real compatible host renders the same read-only fixture data;
HTML escaping and CSP tests pass; stale/empty/malformed tool results fail
closed; clients without UI still receive usable text/structured tool results;
no bridge to localhost, filesystem, KiCad mutation, or arbitrary URL fetch is
exposed; threat review and human signoff occur before any production opt-in.

Sources:
- <https://apps.extensions.modelcontextprotocol.io/>
- <https://developers.openai.com/plugins/build/chatgpt-ui>

## MCP Tasks (long-running work proof)

The hermetic, read-only draft protocol state-machine and pinned SDK 2.2.0
synchronous compatibility probe are described in
[the isolated Tasks research evidence](mcp-tasks-readonly-probe.md).
This does **not** enable production Tasks or attest real host support.


The MCP Tasks draft for protocol 2026-07-28 introduces task handles and
`tasks/get`, `tasks/update`, `tasks/cancel`. A future **disposable test fixture**
could model a long-running *read-only* ERC/DRC summary with a bounded deadline,
TTL, poll interval, cancellation and explicit interrupted/error terminal states.

*Acceptance:* determine real host support first; negotiate extension capability
per request; never expose a task handle without host opt-in; scope/expire state
per authenticated caller; prevent cross-session replay and confused-deputy
execution; implement restart/duplicate-poll/idempotency semantics; retain
ordinary synchronous MCP behavior when Tasks is unavailable; verify cost/CPU
bounds and security/cleanup. Any mutating KiCad Task requires an additional
separate design review and cannot be inferred from read-only success.

Source: <https://tasks.extensions.modelcontextprotocol.io/specification/draft/tasks>

**Explicit non-goals in this tranche:** new production capabilities, task queues,
hosted relay, unattended schematic/PCB writes, marketplace submission,
deployment, and any claim of real-host compatibility without actual smoke logs.

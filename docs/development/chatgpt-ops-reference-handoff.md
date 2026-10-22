# ChatGPT–Ops reference-board preflight (non-executing)

Issue #1214 requires a real clean-start benchmark runner with complete agent
attempt accounting. The existing Claude-only executor, cost gate and existing
initial-phase wrapper remain unchanged.

The additional preflight selects chatgpt-ops for an external ChatGPT session
that will use connected Ops device tools. It does not launch ChatGPT,
reserve an attempt, perform mutations, pay a provider, synthesize an agent
log, or publish an attempt. Valid configuration returns handoff_required,
not a successful PCB design.

From a clean checkout, for an unused attempt number:

    uv run python scripts/check_reference_board_attempt_readiness.py \
      --board-id stm32f072-usbc --attempt-number 4 --phase schematic \
      --agent-runtime chatgpt-ops \
      --ops-server-name kicad-msi-schematic-review \
  --approved-source-revision <owner-approved-40-character-Git-SHA>

## Live tool-surface attestation (read-only; no attempt)

After the offline check reports `handoff_required`, verify the **exact actual
MCP tool inventory**, not just the server configuration:

```sh
uv run python scripts/attest_reference_ops_tool_surface.py \
  --board-id stm32f072-usbc --attempt-number 4 --phase schematic \
  --ops-server-name kicad-msi-schematic-review \
  --approved-source-revision <owner-approved-40-character-Git-SHA>
```

The source SHA must be approved independently of the local checkout
(for example, from the explicitly reviewed/merged GitHub commit).
Do **not** populate this argument by blindly accepting `git rev-parse HEAD`
from the same source being tested. An absent, malformed or differing SHA
blocks `chatgpt-ops` readiness with `source_revision_not_reviewed`; a
checkout whose identity cannot be resolved still blocks with
`source_revision_not_reproducible`. This is an **exact per-revision
pin**, not a hardcoded value embedded in code that would go stale on merge.

The command repeats the source/input/runtime preflight, revalidates the pinned
Ops launch descriptor immediately before invoking it, starts only an MCP
`initialize` plus `tools/list` session with a bounded timeout, and compares
all returned names against the exact reviewed phase allowlist. Missing, extra,
duplicated tools or an unreachable server yield `status=blocked` and exit 2.
Its matching result remains `handoff_required` with
`tool_surface_attested=true`, `executes_agent=false`,
`attempt_reserved=false` and `counts_as_task_success=false`.

This does not run an agent, reserve an ID, produce a client/session log or
attest later changes to the server. The actual benchmark still requires
independently captured paired client/server observations and all native
validation and cost/permission gates described below. Run from the **same
reviewed checkout** that the Ops descriptor points to; a different source tree
must fail closed rather than inheriting a shared server.

The named local Ops MCP server must be enabled, permission-restricted, stdio,
launched from this exact checkout, and use the reviewed
schematic_authoring/write profile/mode, no-dev installation and the
phase-gated Python module in reference_ops_server. The gateway restricts both
MCP discovery AND server-side execution to the canonical reviewed tool set.
The schematic phase now exposes the deliberately narrow
`sch_get_wires` + `sch_delete_wire` recovery pair. First inspect wire UUIDs,
then delete only the explicitly selected segment, check
`sch_get_connectivity_graph`, and rerun ERC; neither a successful deletion
nor a lower ERC count alone proves that USB D+/D− remain separated. Broad
symbol deletion is still excluded from this benchmark phase. A server pinned
to the older 35-tool phase must fail exact-source preflight when used with
this expanded 37-tool reviewed revision.
The underlying general purpose schematic_authoring server exposes more tools
and is NOT a valid benchmark server. It must not inherit a preexisting PCB Editor IPC socket.
A shared review/build server is not an isolated schematic run.
Manufacturing is never unlocked by this path.

The successful handoff result is ONLY configuration and source/input
preflight. Before attempting a board run, independently verify the live
server's permitted tool inventory, match it to the maintained reviewed
execution ceiling, confine all writes to a new scratch directory, and capture
authentic tool calls/results with complete sanitized logs usable by existing
#729/#730 validation. If the live tool boundary or recorder cannot be
attested, do not execute or claim success. A clean preflight does not waive
cost/provider or manufacturing approval.

## Optional server-observed tool trace (experimental infrastructure)

The reviewed stdio host can record an exclusive metadata-only
ops-mcp-trace.jsonl when BOTH of these variables are explicitly configured:

- KICAD_MCP_REFERENCE_ATTEMPT_ID: a reserved attempt identifier
- KICAD_MCP_REFERENCE_TRACE_PATH: an unused absolute filename under the
  checked-out repository's .dev-tools/reference-agent-runs tree,
  ending in the matching attempt ID directory / ops-mcp-trace.jsonl

The attempt directory must already exist and be private (0700). The
trace is created exclusively with owner-only permissions (0600). Existing
files/symlinks are rejected; data is never overwritten.

The recorded events use the reference-agent-log.v1 event shape but this
metadata-only trace is NOT an official agent-log.jsonl or a full ChatGPT
session transcript. The MCP v2 server middleware records tool names, sequence,
timestamps, call correlation and success/failure only. It never stores tool
inputs, responses, prompts, KiCad project contents or secrets. The canonical
scorer still requires an independently reconciled client session record,
native validations and a valid attempt manifest. An MCP tool call succeeding
does not imply benchmark or manufacturing success.

The recorder fails closed if the trace cannot be created or written. If
writing its result event fails after a mutation, the mutation outcome remains
unknown until native readback; do not infer rollback.

Do not enable this recorder on any shared review/build session or create an
official attempt-004 record during a smoke test. A disposable smoke checks
37-tool discovery, a successful version query, blocked unreviewed DRC-rule
deletion, and four ordered events with the denied tool result as failed.

## Validate a completed server trace (not a benchmark score)

After stopping the isolated trace-enabled MCP host, inspect its owner-private
metadata ledger with the read-only validator:

    uv run python scripts/validate_reference_ops_trace.py \
      --trace /absolute/isolated/attempt-dir/ops-mcp-trace.jsonl \
      --attempt-id attempt-004 --phase schematic

The validator checks canonical event schema, approved phase tool names,
attempt identity, uninterrupted event sequence, timestamps, server-observed
provenance and matched call/result IDs. It rejects unfinished calls,
duplicated results, extra fields, and public or symlinked files.
A passing result is server_trace_valid with SHA-256 digest, call counts
and counts_as_task_success=false. Invalid or truncated evidence is
blocked (exit code 2).

This does NOT authenticate ChatGPT or prove an electrical design succeeds.
Do not publish an official benchmark attempt from server trace alone;
complete client transcript reconciliation and native ERC/DRC still apply.

## Optional client/server metadata comparison — not authenticated

A separate client-observed ledger, if actually exported by an independent
client or Ops recorder, may be supplied as an owner-private
`ops-client-observed.jsonl` beside a previously validated
`ops-mcp-trace.jsonl`, with the same attempt ID.

Client events use the existing `pcb-reference-agent-log.v1` format,
strictly sequential `tool_call` and `tool_result` pairs, and details:

- `provenance: client_supplied_ops` (an unverified claim)
- `request_id: null` on calls and the paired call sequence on results

Only sequential calls are comparable in this initial diagnostic. The tool
does not guess correlation when calls overlap, authenticate client identity,
or infer ChatGPT authorship from a manually created file.

```bash
uv run python scripts/reconcile_reference_ops_events.py \
  --server-trace /absolute/private/attempt/ops-mcp-trace.jsonl \
  --client-events /absolute/private/attempt/ops-client-observed.jsonl \
  --attempt-id attempt-004 --phase schematic
```

This checks path restrictions, paired records and exact tool names/outcomes.
Mismatch yields `blocked` (exit 2). Match yields
`client_server_matched_unattested`, always
`counts_as_task_success=false`, and both SHA-256 digests.

**Never synthesize client observations from server trace data.** The
client-side export must be collected independently, and cryptographic
authenticity / session continuity still need separate assurance. This
does not write `agent-log.jsonl`, approve manufacturing, or enter the
#729/#730 task-success denominator.

## Independently observed Ops Gateway audit witness

The VPS Ops Gateway audit store is a second, independently operated
observation point for incoming ChatGPT tool calls, distinct from the MSI
KiCad MCP server trace. For a one-off scoped smoke run, export only an
actual, read-only SQLite audit snapshot filtered to the uniquely named
device MCP server. NEVER export tool arguments, client IDs, errors,
credentials, prompt text or tool response bodies.

Export exactly these non-secret fields: id, at, tool, device, status,
duration_ms. The gateway witness schema ops-gateway-audit-witness.v1 also
contains its device, tool-prefix, source and capture timestamp and
an anonymous client_count. Place it as ops-gateway-audit.json in the
private reserved .dev-tools/reference-agent-runs/TEST/ directory with
permissions 0600.

For a private non-benchmark smoke run:

    uv run python scripts/reconcile_reference_ops_gateway_audit.py \
      --server-trace /abs/checkout/.dev-tools/reference-agent-runs/TEST/ops-mcp-trace.jsonl \
      --gateway-audit /abs/checkout/.dev-tools/reference-agent-runs/TEST/ops-gateway-audit.json \
      --attempt-id TEST --phase schematic \
      --server-name kicad-msi-schematic-e2e-20261020

The verifier checks the server trace first, then checks the VPS witness
against all observed calls, ordered tool identities, device, per-call
status, monotonic audit IDs, time and duration ranges, private file
permissions and exact reserved paths. It rejects unrecognized fields,
including possible secret or client-identity fields.

The resulting status gateway_server_matched_unattested means independently
observed *tool metadata agreement only*. There is no gateway-generated
cryptographic signature or complete authenticated ChatGPT model transcript
in this witness. Never synthesize the gateway witness from the server
trace; never record it as a reference-board task success. Source-backed
benchmark execution and scoring still require the rest of #1214/#730/#729.

## Signed Gateway-to-KiCad server trace reconciliation (non-scored)

Use the maintained `scripts/reconcile_reference_ops_signed_witness.py` verifier
only after **both** a real Ops Gateway `ops-mcp-witness.v1` export and an
independently started, opt-in `ops-mcp-trace.jsonl` server trace exist.
Store the exact exported JSON (not rewritten, reformatted or invented metadata)
as `signed-gateway-witness.json` alongside the private `ops-mcp-trace.jsonl`
under an exclusive `.dev-tools/reference-agent-runs/<run-id>/` directory.
The server must have been started with `KICAD_MCP_REFERENCE_ATTEMPT_ID` and
`KICAD_MCP_REFERENCE_TRACE_PATH` **before** the ChatGPT invocation.
Neither recorder may copy events from the other.

The reviewer must obtain the Ed25519 SPKI and its SHA-256 key ID **from a
trusted independent Gateway/operator channel**, not exclusively from the
signed export. Both are mandatory parameters; omitting either fails closed.
Example (values must be separately reviewed for each production signer):

```sh
python -m scripts.reconcile_reference_ops_signed_witness \
  --server-trace "$PRIVATE_RUN/ops-mcp-trace.jsonl" \
  --signed-gateway-witness "$PRIVATE_RUN/signed-gateway-witness.json" \
  --attempt-id "$RUN_ID" --phase schematic \
  --server-name kicad-msi-signed-trace-v37 \
  --nonce "$VERIFIED_RUN_NONCE" \
  --trusted-public-key-spki "$INDEPENDENTLY_PINNED_BASE64_SPKI" \
  --trusted-key-id "$INDEPENDENTLY_PINNED_SHA256" \
  --consume-nonce
```

The verifier delegates **all** native server trace identity/allowlist/permission
checks to `validate_reference_ops_trace`, then enforces the signed envelope's
exact schema, signature, nonce/target/key pin, ordered call/result pairs, terminal
statuses and independent server/clock/duration alignment. It refuses unknown
fields, incomplete/reordered/interleaved or mismatching calls and symlinked or
non-private evidence. `--consume-nonce` writes 0600 replay markers with
exclusive creation in the private run directory **and** a 0700 per-checkout
nonce registry; later validations of the same nonce are refused even if another
run directory is used in that checkout. Never copy/remove ledgers to reset an
accepted run. Cross-checkout/cross-device reuse requires a separately managed
canonical benchmark consumption ledger; this local guard is not global authority.
Without `--consume-nonce`, the command performs a non-mutating verification
and does not constitute final benchmark acceptance.

A valid result is
`signed_gateway_server_matched_non_scored`, with
`counts_as_task_success=false` and
`unique_chatgpt_conversation_attested=false`. Gateway OAuth authenticates
the **client**, not an individual ChatGPT conversation. This command cannot
reserve or score an official attempt, replace real schematic/PCB work,
waive ERC/DRC/manufacturing restrictions or authorize a paid provider model.
Existing unsigned Gateway audits remain
`gateway_server_matched_unattested` and retain their old verifier.

## Stage-two live KiCad GUI readiness (read-only; PCB phase only)

The offline source/runtime preflight and the MCP tool-list attestation intentionally
**do not prove a running KiCad GUI can answer IPC**. They also do not inspect or
mutate an arbitrary user's active board. Once an **isolated** PCB Editor is
started and its expected fixture board is open, require this additional gate
**before any PCB-phase live mutation or a scored design attempt**:

```sh
uv run python scripts/check_reference_board_attempt_readiness.py \
  --board-id stm32f072-usbc --attempt-number 4 --phase pcb \
  --agent-runtime chatgpt-ops --ops-server-name REVIEWED_PRIVATE_PCB_SERVER \
  --approved-source-revision REVIEWED_40_HEX_SHA \
  --require-live-gui \
  --ipc-socket ipc:///absolute/private/tmp/kicad/api.sock \
  --expected-live-board-name isolated-reference.kicad_pcb
```

For a direct, phase-independent diagnostic, run:

```sh
uv run python scripts/check_reference_live_gui_readiness.py \
  --ipc-socket ipc:///absolute/private/tmp/kicad/api.sock \
  --expected-board-name isolated-reference.kicad_pcb
```

Both commands are read-only, use a bounded 3-second IPC client timeout and
require an actual `get_version()` and `get_board()` response, KiCad 10,
and the expected board identity. The stage-two gate is **opt-in and applies
only to an already-launched isolated PCB phase**; it must not block initial
schematic phases, which legitimately start without a GUI. The standard offline
`ready` or `handoff_required` response **never claims** live GUI readiness:
`live_gui_attested=false` unless stage two was explicitly requested and passed.

A private IPC socket may exist while KiCad is stalled behind its first-start
**“Welcome to KiCad 10.0”** setup wizard or another modal. The native API
returns `AS_NOT_READY`, which this gate classifies as
`kicad_gui_not_ready` with `status=blocked` and exit 2. The operator must
complete any wizard **in that private GUI session** and rerun the check; do not
force global GUI restarts, switch another user's open board, or mark the attempt
as a design failure. Missing/stale sockets, IPC errors, incompatible GUI
versions and wrong board identities also fail closed with reason codes and
without exporting host paths or error details.

The readiness probe checks the currently selected board identity but does **not** independently certify operating-system/GUI isolation. Use a separate reviewed sandbox/session control for that requirement.

A successful ready result is permission to **continue eligibility review**,
not proof of a successful agent-run reference board, a scored attempt or an
approved physical manufacturing release. The exact same live session must be
verified again if the socket, editor, board or fixture changes. Independent
KiCad `pcbnew` binding availability is a separate verification prerequisite
for tools that rely on native reopen checks; a Python MCP virtualenv need not
contain system-only `pcbnew` when the independent verifier uses `/usr/bin/python3`.

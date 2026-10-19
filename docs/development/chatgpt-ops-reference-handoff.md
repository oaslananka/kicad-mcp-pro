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
      --ops-server-name kicad-msi-schematic-review

The named local Ops MCP server must be enabled, permission-restricted, stdio,
launched from this exact checkout, and use the reviewed
schematic_authoring/write profile/mode, no-dev installation and the
phase-gated Python module in reference_ops_server. The gateway restricts both
MCP discovery AND server-side execution to the canonical reviewed tool set.
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
35-tool discovery, a successful version query, blocked unreviewed DRC-rule
deletion, and four ordered events with the denied tool result as failed.

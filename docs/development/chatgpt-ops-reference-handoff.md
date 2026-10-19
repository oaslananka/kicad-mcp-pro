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

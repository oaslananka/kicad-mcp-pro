# Architecture

The project is organized as a src-based Python package with:

- `config.py` for settings and path safety
- `discovery.py` for CLI and project detection
- `connection.py` for KiCad IPC lifecycle
- `tools/` for domain-specific MCP tools
- `resources/` and `prompts/` for MCP-native context surfaces

## Runtime Model

The v2 runtime is no longer just "call a KiCad command and trust the result".
It is structured around four layers:

1. Intent
   - project-scoped design assumptions persisted by `project_set_design_intent()`
   - resolved design-spec view available through `project_get_design_spec()`
   - connector refs, decoupling pairs, power-tree refs, analog/digital groups,
     sensor clusters, RF keepouts, critical nets, and fab profile hints
2. Builder
   - schematic, PCB, routing, and export tools that mutate or inspect the active design
3. Critic
   - resources and prompts that expose quality status and a prioritized fix queue
4. Gate
   - hard release decisions made by the validation surface

## Quality Gate Stack

`project_quality_gate()` is the top-level release contract. It aggregates:

- `schematic_quality_gate()`
- `schematic_connectivity_gate()`
- `pcb_quality_gate()`
- `pcb_placement_quality_gate()`
- `pcb_transfer_quality_gate()`
- `manufacturing_quality_gate()`
- footprint parity checks

The release contract is intentionally strict:

- `export_manufacturing_package()` is hard-blocked unless the full project gate is `PASS`
- low-level exports remain available for debugging and iteration
- agents are expected to use the fix queue and re-run gates after each repair pass

## DRC Execution Contract

`kicad_mcp.validation.drc_runner` is the canonical execution boundary for
`kicad-cli pcb drc`. DFM and validation tools may keep thin compatibility
wrappers, and the tray action delegates directly to the same service. Consumers
must not rebuild command variants, parse report files, or classify process
results independently.

The typed runner result has four states:

- `unavailable`: the CLI, board input, output path, or generated report could not
  be used. A non-zero exit with an otherwise clean report is also unavailable.
- `findings`: a valid report contains DRC violations, unconnected items, or
  legacy courtyard findings. A non-zero `--exit-code-violations` result remains
  a design finding rather than an environment failure.
- `clean`: a valid report contains no actionable findings and the command
  completed successfully.
- `malformed`: output exists but is invalid JSON or violates the expected DRC
  list schema. Malformed output must never be interpreted as a clean report.

Policy-specific PASS/WARN/FAIL rendering remains in each caller. The shared
runner owns stale-output removal, supported command variants, return-code
interpretation, JSON loading, and base result classification. Public MCP tool
names and schemas are unchanged. The intentional compatibility correction is
that malformed DRC JSON can no longer appear as a clean result: `run_drc()`
returns an explicit configuration failure, while DFM surfaces a warning and
skips false zero-finding checks.

## Health Surface

The MCP resource layer exposes the current review state as text-first surfaces:

- `kicad://project/quality_gate`
- `kicad://project/fix_queue`
- `kicad://schematic/connectivity`
- `kicad://board/placement_quality`

These resources exist so an agent can inspect, criticize, fix, and re-check without
inventing its own hidden state model.

## IPC Command Queue

Live KiCad GUI mutations must pass through `kicad_mcp.ipc.command_queue` so
stateful IPC operations are serialized, retried only when safe, and journaled
with a correlation id. The initial routed operations include board save, zone
refill, item deletion, board commit/revert actions, and PCB title-block edits.

File-backed/headless writes such as schematic S-expression transactions are
intentionally outside the IPC queue: they use project-local atomic file writers
and rollback checkpoints instead, so they continue to work when KiCad is not
running.

## Placement Review

Placement review is intentionally split in two:

- `pcb_placement_quality_gate()` blocks hard geometry/context failures
- `pcb_score_placement()` reports softer heuristics such as density, spread,
  power-tree locality, analog/digital proximity, and sensor clustering

This keeps release gating deterministic while still letting agents optimize placement quality
before a hard failure appears.

## Benchmark Corpus

Release behavior is pinned by a small benchmark/failure corpus under
`tests/fixtures/benchmark_projects/`.

The benchmark suite ensures that:

- pass fixtures can reach release export
- known failure fixtures remain blocked
- the correct subsystem is blamed

That corpus is part of the architecture, not just a test convenience. It is the
regression harness for agent-to-tool synchronization quality.

## Domain Split Guard

Large implementation files are being split incrementally without changing public
MCP tool names. The first extracted slices are:

- `kicad_mcp.tools.schematic_constants` for schematic geometry, layout, power-net,
  and public-tool constants.
- `kicad_mcp.models.visual_qa`, `sch_transaction`, and `contract_verifier` for
  pure, file-backed engines.
- `kicad_mcp.ipc.command_queue` for serialized KiCad IPC mutations.
- `kicad_mcp.companion.context` for dependency-free companion plugin helpers.

`scripts/check_architecture_boundaries.py` keeps those helpers import-light and
cycle-free. It is part of `check:meta`, so future refactor slices must preserve
the extracted-domain boundaries while the monolith split continues.

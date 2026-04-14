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

## Health Surface

The MCP resource layer exposes the current review state as text-first surfaces:

- `kicad://project/quality_gate`
- `kicad://project/fix_queue`
- `kicad://schematic/connectivity`
- `kicad://board/placement_quality`

These resources exist so an agent can inspect, criticize, fix, and re-check without
inventing its own hidden state model.

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

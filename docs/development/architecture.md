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

## PCB Segment Geometry Contract

`kicad_mcp.pcb.geometry.track_segment_length_mm()` is the canonical length
calculation for straight PCB track segments used by routing, EMC, signal-
integrity, and power-integrity analysis. It reads explicit `start`/`end` point
coordinates through the repository's `_coord_nm()` compatibility helper,
converts each delta with `nm_to_mm()`, and applies Euclidean distance in
millimetres. A cached or provider-specific length field is not used.

The contract is deliberately limited to straight segments. Arc, curved, and
polyline objects require a separately named implementation that accounts for
their full geometry; callers must not approximate them as endpoint chords.
`point_xy_mm()` is the shared coordinate wrapper for object positions and uses
the same nanometre compatibility path. Missing or non-numeric coordinates
raise `BoardGeometryError` instead of producing a zero length or origin.

Board-envelope helpers remain domain-specific: EMC derives live Edge.Cuts
bounds, power-integrity may fall back to a footprint envelope, and file-backed
outline parsing operates on S-expressions rather than live point objects. Those
policies must not be collapsed into a generic point/segment helper.

The canonical calculation preserves the former EMC/SI/PI precision exactly.
The previous routing helper rounded the Euclidean result to the nearest
nanometre before conversion, so representative outputs remain compatible
within 0.5 nm (`5e-7` mm). New code must use the unrounded canonical result.

## Shared PCB Helper Extension Policy

Correctness-sensitive PCB helpers have one canonical owner:

- `kicad_mcp.pcb.board_access` owns live board collection reads and preserves the
  distinction between a successful empty collection and an unavailable or
  unreadable board API.
- `kicad_mcp.pcb.geometry` owns KiCad point conversion and straight-segment
  track length in millimetres.
- `kicad_mcp.validation.drc_runner` owns DRC command variants, stale-output
  handling, report parsing, and base `unavailable` / `findings` / `clean` /
  `malformed` classification.

Callers import these helpers rather than defining private variants. DFM and
validation may keep thin `_run_drc_report` compatibility wrappers because they
translate the typed runner result into different public policy/rendering
contracts; those wrappers must delegate to the same runner and must not execute
`kicad-cli`, parse JSON, or classify the report independently.

A genuinely domain-specific calculation is allowed only under a distinct name
that communicates its additional policy. For example, live Edge.Cuts bounds, a
footprint-envelope fallback, and file-backed S-expression bounds remain
separate because they consume different sources and answer different questions.
The reason and unit semantics must be documented next to the implementation.

`scripts/check_architecture_boundaries.py` enforces this narrow policy in CI and
pre-push checks. It scans top-level production functions only, requires each
canonical symbol to have exactly one owner, and rejects the legacy private
board-access and geometry names removed by the consolidation. Protocol methods,
nested test fixtures, and distinctly named domain-specific helpers are not
flagged. A failure identifies the symbol and every production file location,
then points contributors to the canonical import or distinct-name remedy.

The regression evidence is intentionally split by failure mode:

- `tests/unit/test_pcb_board_access.py` covers empty data versus access failure.
- board inspection/resource tests cover caller fallback and user-visible failure
  semantics.
- `tests/unit/test_drc_runner.py` covers shared DFM/validation delegation and all
  four DRC result classes.
- `tests/unit/test_pcb_geometry.py` covers supported point/segment shapes,
  malformed inputs, and the documented 0.5 nm routing compatibility tolerance.
- `tests/unit/test_shared_helper_architecture.py` exercises actionable duplicate
  guard failures and false-positive exclusions.

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

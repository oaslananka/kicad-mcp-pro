# Incremental project state — experimental v0 (#944)

This is a **bounded, opt-in domain-state pilot**, not completion of the
large-project performance epic. KiCad native schematic/board/project files are
always authoritative; cached state is never validation evidence.

## Current contract

`kicad_mcp.project.incremental_state.PersistentProjectState`:

1. Creates a baseline **after** a trusted native parse into `IRCircuit` using
   `rebuild(root, native_sources, circuit)`; the API does not parse or write
   native KiCad documents.
2. Inventories and hashes all tracked native `.kicad_sch`, `.kicad_pcb`,
   `.kicad_pro`, and `.kicad_dru` files, including hierarchical subfolders.
   A new/missing/renamed sheet, symlink, unexpected byte change, project switch,
   parser/KiCad-version change, or incompatible schema triggers `StateRebuildRequiredError`.
3. Persists a deterministic Engineering Graph v1 snapshot, exact per-entity
   SHA-256 hashes, a local root identity, a required host-supplied KiCad/parser
   compatibility key, derived-analysis dependency stamps and a **32-entry bounded
   journal** to an explicit `.kicad-mcp-cache/*.json` sidecar via atomic rename.
   Reopens only when the graph, schema, inventory and exact native hashes agree.
4. Uses `prepare_native_edit()` before the caller's native mutation and
   `apply_native_edit(token, before, after, expected_new_hashes=...)` after an
   *authoritative native read-back*. It delegates bounded attribute-only graph
   updates to the existing #940 `update_graph_from_circuit` seam. Unsupported
   structural/net/pin/PCB edits **require a clean full rebuild**, except for the
   explicitly opted-in saved PCB translation path described below.
5. Invalidates modified/impacted graph facts and their derived stamps. A stamp
   records dependencies, **not** analysis output or verified measurement.
   `derived_is_current` verifies native bytes before reporting freshness.

This v0 object is owned by one local project process. It assumes **trusted
project cache storage and exclusive native mutation/read-back ownership**.
The legacy `rebuild()` path remains deliberately single-sheet. Merely hashing
all native files does not establish hierarchy completeness. The opt-in #1141
path captures a native XML netlist in isolated staging, verifies its sheet
paths and symbol-instance UUIDs against the hashed source files, and preserves
those identities as graph native links. Repeated instances remain distinct.
Unsupported schema, incomplete identity and connectivity, unsafe paths, and
source changes during capture fail closed.

SHA-256 guards cache freshness and detects accidental changes, but is not an
authenticity signature against a malicious actor able to replace both the
sidecar and project data. No background file watcher, OS sandbox, cross-process
locking, dynamic adapter loading or distributed cache is provided.

For a save, the final source verification runs after staging and flushing the
temporary sidecar, immediately before publication. A detected source change
or interrupted save leaves the previous sidecar in place; a later verified
reopen rejects it if native sources changed. During reopen, source verification
follows graph, journal and derived-stamp validation. Independent readers of an
atomically replaced sidecar with unchanged native sources see complete old or
new documents. Abandoned hidden temporary files are not accepted as sidecars.
This is not a guarantee against edits after the final verification, simultaneous
native writers, or sudden power loss; the caller must still own mutation and
read-back.

Example (caller supplies independently parsed authoritative `circuit` for a
single-sheet design; its sheet hierarchy contains at most the root entry):

```python
from pathlib import Path

from kicad_mcp.project.incremental_state import PersistentProjectState

root = Path("/trusted/local/project")
sources = ("top.kicad_sch", "top.kicad_pcb", "top.kicad_pro")
state = PersistentProjectState.rebuild(
    root, sources, circuit,
    compatibility_key=detected_kicad_and_parser_versions,
)
state.save_atomic(root / ".kicad-mcp-cache/graph.json")
reopened = PersistentProjectState.load_verified(
    root, root / ".kicad-mcp-cache/graph.json",
    project_key=state.project_key, native_sources=sources,
    compatibility_key=detected_kicad_and_parser_versions,
)
```

## Opt-in native hierarchy (#1141)

Use the existing trusted KiCad CLI runner and an explicit inventory of all
native sources. The runner must return `(exit_code, stdout, stderr)` and enforce
a timeout; the caller retains exclusive mutation/read-back ownership.

```python
from kicad_mcp.project.incremental_state import capture_native_hierarchy

snapshot = capture_native_hierarchy(root, "top.kicad_sch", sources, run_cli=run_cli)
state = PersistentProjectState.rebuild_native(
    snapshot, compatibility_key=detected_kicad_and_parser_versions,
)
state.save_atomic(root / ".kicad-mcp-cache/graph.json")
reopened = PersistentProjectState.load_verified(
    root, root / ".kicad-mcp-cache/graph.json",
    project_key=state.project_key, native_sources=sources,
    compatibility_key=detected_kicad_and_parser_versions,
    native_snapshot=snapshot,
)
```

Supply a fresh authoritative capture for reuse after reopening the project.
Native reopen constructs the graph once from this capture and compares the
complete canonical graph document with the sidecar before accepting its
metadata and entity hashes. A noncanonical or mismatched sidecar is discarded,
not silently repaired. The root-only path retains its existing loader.
For an attribute edit, obtain `prepare_native_edit()` before mutation, capture
again afterward, and call `apply_hierarchy_edit(token, before, after)`.
Edit tokens are scoped to the live state instance and are never persisted:
cloned projects, reopened sidecars, rebuilt states and compatibility upgrades
must obtain a new token before editing, even when source hashes match. Changes
to instance identity or topology require `rebuild_native()` instead. The
adapter covers exported native netlist connectivity, not geometry, all library
pins, inferred power rails or ERC/DRC. Multi-unit symbols whose identity cannot
be validated against the source sheet are rejected rather than guessed.

## Opt-in saved PCB footprint graph (schema v2)

The default schematic Engineering Graph v1, its canonical IDs and existing
sidecar documents remain unchanged. The explicit native PCB projection uses
graph schema v2 (the enclosing state envelope remains v1). It adds
`pcb_footprint` entities keyed by project, relative board path and native
footprint UUID, including distinct objects with duplicate references. No
schematic-to-PCB link is inferred from reference text. Pad/track/net geometry
and relationships are not modeled.

```python
from kicad_mcp.pcb.footprint_index import FileFootprintIndex
from kicad_mcp.project.incremental_state import capture_native_pcb

index = FileFootprintIndex()
pcb = capture_native_pcb(root, board_name, sources, index=index)
state = PersistentProjectState.rebuild_native(
    snapshot, compatibility_key=physical_graph_compatibility_key, pcb_snapshot=pcb,
)
token = state.prepare_native_edit()
# Caller performs an authorized native translation and saves the board.
updated = capture_native_pcb(root, board_name, sources, index=index)
state.apply_pcb_placement(
    token, updated, native_uuid=target_uuid, x_mm=target_x, y_mm=target_y,
)
state.save_atomic(root / ".kicad-mcp-cache/graph.json")
```

The host-supplied compatibility key must identify the physical v2 projection
and native parser/runtime versions. Capture uses the same bounded footprint
index as ordinary saved-board listing, with exact source inventory hashes
and guarded reads. The edit checks the same state-instance token, exact
source inventory, board identity, ordered footprint inventory, byte hashes
of all unaffected footprint blocks and the rest of the board, and the
requested X/Y. Only the selected footprint's root X/Y tokens may change;
rotation, pad, track, net, addition/deletion, another footprint, formatting
changes outside those tokens, or uncertain state require rebuild. A single
updated entity is constructed/hashed; the complete inventory is still
scanned and file bytes hashed. All stamped derived analyses are invalidated
conservatively because physical connectivity dependency edges are not yet
modeled. Schematic edits in a v2 state likewise invalidate all existing
stamps and cannot hide a non-schematic file change.

Reopen requires both fresh authoritative hierarchy and PCB captures, the
same source hashes and the exact canonical graph document. V1 documents
cannot contain physical entities; v2 sidecars cannot reopen via the v1-only
path. Read-only capture does not create a sidecar or modify native files.
The caller retains exclusive edit/read-back ownership and must explicitly
opt in to persistence. The ordinary file-backed listing path still writes
nothing. No unsaved GUI state, arbitrary concurrent mutation, or DRC/geometry
validity is inferred from saved bytes.

## Local native save integration

Explicitly set `KICAD_MCP_ENABLE_PERSISTENT_PCB_STATE=true` in trusted server
configuration for a local stdio session in write/experimental mode with a
configured KiCad project, PCB and root schematic. The feature defaults to off.
The project must match the live board's native project path, name and file;
remote IPC endpoints and HTTP sessions are not supported.

Use the existing `pcb_save` tool to build/reopen the saved graph, move a
footprint by unique reference or native UUID, and explicitly call
`pcb_save` again. The normal serialized save/transaction guard remains the
native mutation authority. No extra native save is issued by the cache.
Unsaved edits do not publish a graph. A verified single X/Y translation
updates one node; unsupported or external changes require a fresh native
capture and rebuild. The tool reports the saved graph as rebuilt, reopened,
unchanged, updated, or unavailable separately from native save success.
A cache error does not replay an already completed native save. A failed or
ambiguous native save cannot publish a new graph. Project/connection changes
evict the in-process state; a previous sidecar is never used as current
without native hash verification. The index shared with file-backed listing
remains read-only there. The sidecar is `.kicad-mcp-cache/physical.json`;
deleting it while the server is idle is safe and the next explicit save
rebuilds or recreates verified state. Do not use the opt-in on a project with
other concurrent native writers.

The maintained Linux private-GUI acceptance test starts a disposable editor
in its own mount/PID/network namespace and Xvfb display, verifies the IPC
peer and native project identity, and exercises three move/save cycles and
verified reopen. It requires installed KiCad, system pcbnew Python, bwrap,
Xvfb and the repository's Python environment. See the native benchmark
documentation for the command and limitations.

## Validated now versus still outstanding

Focused tests exercise persistence, deterministic reopen, bounded semantic
component edits, clean-vs-incremental graph equivalence, per-entity invalidation,
source-inventory changes, external edits, symlinks, corrupt schema/graph/journal,
project switches, and a **synthetic 1,024-component IR fixture**. The synthetic
fixture does **not** qualify as a native KiCad hierarchy/PCB benchmark.

The #1141 native hierarchy acceptance tests additionally compare all exported
pin-to-net connections and source instance identities against a pinned real
1,000+ component project and verify bounded updates and structural rebuilds.
See the [native demo benchmark](kicad-large-native-demo-benchmark.md).

Remaining #944 acceptance work includes broader editor/physical object support,
end-to-end latency qualification on representative pinned hardware, reviewed
wall-clock/memory budgets, and concurrent native writer cases beyond the
documented exclusive-owner boundary. Do not claim general production cache
behavior from these bounded tests.

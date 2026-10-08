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
   A new/missing/renamed sheet, symlink, unexpected byte change, project switch
   or incompatible schema triggers `StateRebuildRequiredError`.
3. Persists a deterministic Engineering Graph v1 snapshot, exact per-entity
   SHA-256 hashes, derived-analysis dependency stamps and a **32-entry bounded
   journal** to an explicit `.kicad-mcp-cache/*.json` sidecar via atomic rename.
   Reopens only when the graph, schema, inventory and exact native hashes agree.
4. Uses `prepare_native_edit()` before the caller's native mutation and
   `apply_native_edit(token, before, after, expected_new_hashes=...)` after an
   *authoritative native read-back*. It delegates bounded attribute-only graph
   updates to the existing #940 `update_graph_from_circuit` seam. Unsupported
   structural/net/pin/PCB edits **require a clean full rebuild**.
5. Invalidates modified/impacted graph facts and their derived stamps. A stamp
   records dependencies, **not** analysis output or verified measurement.
   `derived_is_current` verifies native bytes before reporting freshness.

This v0 object is owned by one local project process. It assumes **trusted
project cache storage and exclusive native mutation/read-back ownership**.
SHA-256 guards cache freshness and detects accidental changes, but is not an
authenticity signature against a malicious actor able to replace both the
sidecar and project data. No background file watcher, OS sandbox, cross-process
locking, dynamic adapter loading or distributed cache is provided.

Example (caller supplies independently parsed authoritative `circuit`):

```python
from pathlib import Path

from kicad_mcp.project.incremental_state import PersistentProjectState

root = Path("/trusted/local/project")
sources = ("top.kicad_sch", "power.kicad_sch", "top.kicad_pcb", "top.kicad_pro")
state = PersistentProjectState.rebuild(root, sources, circuit)
state.save_atomic(root / ".kicad-mcp-cache/graph.json")
reopened = PersistentProjectState.load_verified(
    root, root / ".kicad-mcp-cache/graph.json",
    project_key=state.project_key, native_sources=sources,
)
```

## Validated now versus still outstanding

Focused tests exercise persistence, deterministic reopen, bounded semantic
component edits, clean-vs-incremental graph equivalence, per-entity invalidation,
source-inventory changes, external edits, symlinks, corrupt schema/graph/journal,
project switches, and a **synthetic 1,024-component IR fixture**. The synthetic
fixture does **not** qualify as a native KiCad hierarchy/PCB benchmark.

Remaining #944 acceptance work includes a real versioned 1,000+ component
hierarchical KiCad schematic **and** realistically large PCB, native parsing
and editor integration, dependable concurrent-edit/watch semantics, p50/p95
inspect/update/refresh and peak-RSS measurements on that maintained fixture,
baseline evidence with explicit KiCad version/source/fixture hashes, CI
non-regression thresholds, and broader PCB/object-level delta support. Do not
claim latency savings or production-ready cache behavior from IR-only tests.

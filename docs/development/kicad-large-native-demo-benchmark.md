# Real 1,000+ footprint native KiCad inspection baseline

This is a first **real native large-project** performance baseline for #944,
not a complete persistent incremental-state performance or board design result.

## Source / license

The benchmark consumes Antmicro's Jetson AGX Thor baseboard demo, distributed
by KiCad in the `kicad-demos` package. The upstream directory contains the
`Apache-2.0` LICENSE and source README. The current opt-in fixture uses:

- KiCad native demo distribution: 10.0.6;
- PCB source: `jetson-agx-thor-baseboard.kicad_pcb`;
- a native PCB with at least 1,000 footprints and a separately maintained
  set of schematic sources;
- input source hashes pinned in
  `tests/fixtures/native_demo_manifests/jetson-agx-thor-baseboard-kicad10.json`.

**The copyrighted vendor design files are not copied or redistributed in
this repository.** A runner must install the matching KiCad demonstration
package separately. The script rejects unknown or modified input files, any
symlink in the demo directory, a changed license, or a PCB whose native parser
reports fewer than 1,000 footprints.

## Reproduce

On a runner with KiCad 10.0.6 and KiCad's native Python API installed in the
distribution's Python environment:

```bash
/usr/bin/python3 -c 'import pcbnew; print(pcbnew.GetBuildVersion())'
python3 scripts/benchmark_kicad_large_demo.py --repeats 3 \
  --output /tmp/kicad-large-native-inspect.json
```

The benchmark only executes root-owned, non-group/world-writable system
Python and Git binaries from pinned `/usr/bin` paths. It refuses to overwrite
evidence and rejects output inside the source checkout. It copies **only pinned files** into an isolated temporary
directory and rehashes every copy before launching a fresh native `pcbnew`
process for each observation. The external demo is never edited.

The raw report records: project commit SHA, immutable manifest hash, board
SHA-256, exact KiCad native version, native component/track/copper-layer counts,
native board load time, native board inspection time, separate-process **true
peak RSS on Linux**, observations, and nearest-rank p95 and p50. Independent
processes prevent cross-iteration allocator caches from being interpreted as
independent cold loads. The sample count is explicit; a 3-run p95 is only an
initial observation, not a stable release threshold.

## Limitations that remain hard gates

- Native `pcbnew.LoadBoard` and footprint/track count **are not** #940
  incremental graph refresh, mutation/update latency, or cache invalidation.
- Schematic file count shows a real multi-sheet source bundle; it does not by
  itself prove full schematic parser equivalence with the Engineering Graph.
- Nothing in this runner claims DRC/ERC compliance, BOM/manufacturing outputs,
  agent task success, a clean-start design, or a 95% task success KPI.
- No p95/peak-memory regression limit is enforced until a representative
  baseline and CI hardware class are reviewed. Version skew intentionally
  requires refreshing the pinned-input evidence rather than silently treating
  another KiCad demo revision as the same board.
- The native Python worker currently supports Linux only for accurate
  per-process `resource.ru_maxrss` values. Cross-platform runs may be added
  with validated Windows/macOS peak-RSS semantics.

## Native hierarchy acceptance (#1141)

On Linux with the matching pinned demo files and KiCad CLI installed, run:

```bash
KICAD_MCP_NATIVE_HIERARCHY_DEMO=1 uv run pytest \
  tests/integration/test_native_hierarchy_acceptance.py -q -s
```

The test checks native sheet/symbol identity and all exported pin-to-net
connections, a bounded attribute edit against a clean graph rebuild, external
change rejection, structural rebuild and deterministic sidecar reopen. It
uses isolated copies of the pinned sources, and verifies that the originals
remain unchanged. The output includes the manifest hash, native version,
counts, three state-phase timing samples and separate process RSS peaks.
Native capture timings are reported separately; state-phase speedup is not an
end-to-end speedup or a production non-regression threshold.

## Native sidecar reopen comparison (#944)

On KiCad 10.0.8 with the pinned Jetson AGX Thor demo, a verified sidecar
containing the bounded R17 value change was loaded five times per variant,
using the same freshly captured native snapshot and alternating baseline
and candidate order. The baseline loader is from
`603e194846b7b8249453ed150f2296401bcdea98`; the candidate builds the
authoritative graph once and checks the complete canonical sidecar document.
Every result matched the persisted document and all 4,712 native pin-net
connections. All 21 original source hashes were revalidated.

| Loader-only latency (ms) | Baseline | Single authoritative graph |
| --- | ---: | ---: |
| Samples | 2942.134, 2946.121, 2935.243, 2939.532, 2991.632 | 1449.799, 1453.914, 1451.985, 1451.346, 1454.619 |
| p50 | 2942.134 | 1451.985 |
| p95 (nearest rank) | 2991.632 | 1454.619 |

To reproduce, use the pinned demo and capture/edit helpers in
`tests/integration/test_native_hierarchy_acceptance.py` to create and save a
verified native state after the R17 attribute edit. Capture a fresh snapshot
of the edited sources, then time the complete `load_verified` call with that
snapshot and identical sidecar, alternating the baseline and candidate loader
implementations; check returned documents and native parity outside the timer.

The shared capture took 6023.777 ms, outside the loader timer. The shared
process peak RSS was 193836 KiB, not a per-variant memory comparison. These
five local observations do not establish a production p95, an end-to-end
editor speedup, or a CI threshold.

## File-backed footprint listing (#944)

The existing `pcb_get_footprints` file-backed fallback now has a bounded,
in-process listing index scoped to one board path and supported board format.
Every request reads the saved board; matching content hashes allow reuse of
immutable records. After a file change, the board is scanned again and only
changed footprint blocks are decoded. Full native UUIDs identify records, so
duplicate references such as `REF**` do not collapse. The returned
`file:footprint:<uuid>` identifiers are file-backed inspection identifiers,
not live IPC mutation handles. Older files without supported UUIDs retain the
uncached legacy fallback. Invalid supported inventories are not reused.
No sidecar is written by this listing path; live GUI reads, geometry and
connectivity consumers are unchanged.

On KiCad 10.0.8 with the pinned Jetson AGX Thor demo, a diagnostic copy
with a single R17 placement change of +0.1 mm on X was checked against
independent native pcbnew reload and a clean index. All 1,125 footprint UUID,
reference, value, X/Y and layer records matched, including two distinct
`REF**` footprints; all 21 original source hashes remained unchanged.

| Observed operation | Duration (ms) | Recomputed footprint records |
| --- | ---: | ---: |
| Initial saved board read and index | 9866.711 | 1125 |
| Unchanged saved board read and index | 519.895 | 0 |
| Changed saved board read and index | 5216.240 | 1 |
| Warm file-backed listing adapter, page 1 | 659.636 | 0 |
| Independent clean index after edit | 6589.635 | 1125 |

These are single local observations, not population latency or reviewed
regression thresholds. The legacy full-geometry parser exceeded the bounded
diagnostic timeout, so no exact speedup ratio is claimed. The changed board
still requires a full text scan; the work-unit count measures decoded
footprint records, not total I/O or scan work. Diagnostic process peak RSS
was 732256 KiB (including creation of the edited copy), not an isolated
cache-memory measurement. Native save/GUI mutation and persistent physical
PCB graph ingestion are outside this listing acceptance.

## Opt-in physical footprint graph acceptance (#944)

Run the maintained independent native read-back test on the pinned Linux demo:

```bash
KICAD_MCP_NATIVE_PCB_DEMO=1 uv run pytest   tests/integration/test_native_hierarchy_acceptance.py   -k pinned_large_native_pcb_placement -q -s
```

The test copies the pinned sources, captures the native hierarchy, constructs
the physical v2 graph, and compares every UUID, reference, value, position and
layer against a separate trusted system-Python `pcbnew.LoadBoard` read-back.
Three controlled R17 X translations on the disposable saved file must each
update one graph entity, match independent native reload and a clean graph
rebuild, and reopen from an explicitly saved sidecar. All original source hashes
must remain unchanged. This is not a live GUI/native editor save trial.

The report records three samples and p50/nearest-rank p95 for warm capture,
incremental refresh, clean capture/build and verified reopen, process peak
RSS, native version, source SHA and pinned input hashes. The hierarchy
capture is reported separately; independent native read-back is outside the
state-phase timers. The executable deterministic work budgets are 1,125
cold/clean footprint decodes, zero warm decodes and one changed decode and
graph entity per translation. Three local observations do not establish a
hosted CI wall-clock or memory threshold.

The small native GUI save-cycle regression is separate:

```bash
KICAD_MCP_NATIVE_PCB_SAVE_GUI=1 uv run pytest \
  tests/gui/test_pcb_saved_state_native.py -q -s
```

This uses a generated two-footprint board and the maintained repeated-sheet
fixture, never the operator's GUI. It uses bwrap mount/PID/network isolation,
private Xvfb and private config/socket, verifies the kernel IPC peer, then
executes actual MCP move/save/reopen calls. It asserts one graph work unit
per move, no sidecar change before save, and independent native reload parity.
The GUI test is not the representative 1,125-footprint latency benchmark.

## Follow-up for full #944 acceptance

Native schematic hierarchy is an opt-in verified path and file-backed
footprint listing supports bounded record reuse. The experimental v2 saved PCB path now supports the explicit native save
boundary and bounded translation, with maintained repeated cycles and
deterministic work budgets. Remaining work includes broader physical deltas,
reviewed wall-clock/memory thresholds on pinned CI hardware and broader
concurrent-edit acceptance under a documented ownership contract. This
benchmark does not claim general PCB performance or manufacturing readiness.

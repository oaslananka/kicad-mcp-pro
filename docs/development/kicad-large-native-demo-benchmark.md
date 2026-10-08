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

## Follow-up for full #944 acceptance

Integrate the merged #1137 opt-in sidecar with real KiCad schematic and PCB
readbacks for this or another properly licensed large project; report
bounded update work units, invalidation after external edits, clean/full graph
equivalence, p50/p95 inspect and mutation-refresh latency, and true peak RSS.
Only then review nonregression thresholds and promote the benchmark into a
required performance gate.

# Native KiCad fixture-readiness baseline (not a product success claim)

Issue links: #944 (large-project incremental performance) and #730
(real-world reference-board corpus).

The existing repository contains useful KiCad project fixtures, but a
**parseable board**, a **DRC report**, a **benchmark specification**, and a
**successfully produced autonomous reference board** are four different forms
of evidence. Do not combine them into a single "reference boards passing" KPI.

## Reproduce

Use the maintained KiCad 10 CLI in an appropriately provisioned **Linux**
runner. The audit only executes root-owned, non-group/world-writable
`kicad-cli` and `git` from trusted OS system directories; scripts and
arbitrary PATH/virtualenv executables are rejected:

```bash
kicad-cli version
python3 scripts/audit_native_board_fixtures.py --samples 3 \
  --output /tmp/kicad-native-audit.json
```

The command deliberately refuses repository-local output and replacement of
existing audit evidence. Each CLI run gets a private scratch copy of a fixed,
reviewed fixture; native KiCad is **never invoked on the tracked project
directory**, since even a DRC invocation can create local `.kicad_prl` data.

The report includes repository commit identity, individual source SHA-256
digests, actual KiCad CLI version, selected fixture IDs, source-level
footprint count, every CLI DRC process outcome, exit status, finding count,
duration samples, measured p50 and nearest-rank p95. Missing/invalid projects
are recorded as native errors, not omitted. DRC violations are always
recorded as violations, even when the KiCad CLI successfully ran. A timed-out
check is never recategorized as a successful parse.

Only the **DRC command duration** is measured; the report explicitly marks
native peak RSS as **not measured**. The p95 estimate has very low statistical
confidence at the small default sample count. It is **not** the inspect,
mutation, incremental-refresh or memory baseline requested by #944. No
performance gate should be set from it without reviewed multi-run timing and
environment baselines.

## Maintained fixture preflight scope

The initial deliberately finite set includes:

- `mcu`: maintained small MCU benchmark fixture;
- `sensor`: maintained sensor node benchmark fixture;
- `large`: repository fixture named "large-board";
- `esp32-gallery`: gallery schematic/PCB pair.

The `pcb_footprint_source_count` is an explicitly labeled *syntax count*
of PCB `(footprint ...)` records, not a verified schematic component count.
Never label the existing "large-board" as a realistic 1,000+ component
benchmark solely from its filename. A board with DRC findings, a library
setup warning, or a parser error cannot be published as a manufacturing-ready
board from this audit.

## Real-board corpus boundary

The written ESP32-C6, STM32F072 and RP2350 benchmark specifications are
already versioned under `docs/evidence/reference-boards/`. This audit
reports which input files and manifest *entries* exist and their hashes.
Those are **unverified counts**, not independently validated agent logs or
complete project outputs. The canonical publish validator remains:

```bash
uv run --frozen python scripts/validate_reference_board_bundle.py \
  --bundle docs/evidence/reference-boards/stm32f072-usbc/v1
```

A reference board is counted as successful only after the full frozen
task-success contract, native KiCad parse/ERC/DRC, manufacturing
reproducibility, and complete denominator/attempt-manifest validation pass.
Running this lightweight readiness audit never publishes an attempt, approves
a manufacturing release, or changes the score denominator.

## Next real acceptance milestones

For #944, add a **maintained native KiCad** project containing 1,000+
components, multiple real schematic sheets and a large PCB. Record its exact
source hash, KiCad version, inspect/refresh/update samples, p50/p95, true
peak RSS, graph clean-rebuild equivalence and explicit external-edit
invalidation. Review thresholds only after a credible baseline is accepted.

For #730, run the specified board-creation tasks from clean, frozen inputs,
preserve every agent attempt/failure and required ERC/DRC evidence, and publish
at least three successful serious boards with BOM, manufacturing and clean
reproducibility results. Existing toy fixtures and a gallery board are
diagnostic inputs, not replacements for those boards.

# KiCad Fixtures Package

`@oaslananka/kicad-fixtures` owns the deterministic KiCad fixture corpus for
OASLANA-53 / GitHub issue #54. The package is private to this monorepo and is
intended for tests in `apps/vscode-extension`, `packages/mcp-server`, shared
test harnesses, and future contract/visual test packages.

## Layout

```text
packages/kicad-fixtures/
  manifest.json
  fixtures/
    clean-led-kicad10/
    stale-diagnostics-kicad10/
    kicad-10-0-3-regressions/
    erc-power-pin-error/
    drc-courtyard-error/
    unconnected-pcb/
    missing-netlist/
    empty-board/
    empty-project-kicad10/
    no-dru-file/
    multi-sheet-schematic/
    large-board/
    malformed-sch/
    malformed-pcb/
    paths-with-spaces/
    unicode-path-çöğü/
  expected/
    <fixture-id>/
      project-tree.snapshot.json
      diagnostics.snapshot.json
      status.snapshot.json
      erc-report.json
      drc-report.json
      bom.csv
      netlist.net
      board-stats.txt
```

## Fixture metadata

`manifest.json` is the stable index for the package. It records each semantic
fixture ID, source file names, expected DRC/ERC/BOM/netlist state, tags, and
supported KiCad versions through fixture tags such as `kicad10`,
`windows-paths`, `schematic`, `pcb`, `drc`, and `erc`.

The `kicad-10-0-3-regressions` fixture records patch-specific CLI, importer,
export, and custom-padstack probes for the KiCad 10.0.3 release line.

Tests should use semantic fixture IDs from `manifest.json` or the TypeScript
helpers exported from `src/index.ts`. Do not hard-code generated file lists in
product tests.

## Fixture maintenance

Fixture source files and golden outputs are checked in and reviewed explicitly. The
historical fixture generator and root `fixtures:kicad:generate` / `test:fixtures`
scripts are not present in this migrated repository, so do not rely on those old
commands when updating the corpus.

For KiCad canary fixture changes, run the focused contract tests:

```bash
python scripts/run_uv.py run --all-extras python -m pytest tests/unit/test_kicad_canary.py -q
```

Then run the normal repository verification. Live KiCad compatibility evidence from
the repository KiCad canary workflows is authoritative for stable and preview
versions.

## Source Verification

This package uses the repository's existing Node.js 24 runtime, pnpm 11
workspace tooling, TypeScript 5.9, and stable `node:fs` / `node:path` APIs. It
does not introduce external runtime dependencies.

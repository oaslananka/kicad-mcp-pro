# KiCad 10.0.4 Canary Report

**Generated:** 2026-07-03  
**Source script:** `scripts/kicad_canary.py`  
**Evidence directory:** `docs/evidence/kicad-10-0-4/2026-07-03/`  
**Source commit under test:** `ca9941e`  
**Host:** `ops-vps-fra1`  
**OS:** Ubuntu 22.04.5 LTS  
**KiCad package source:** `ppa:kicad/kicad-10.0-releases`  
**KiCad CLI:** `/usr/bin/kicad-cli`  
**KiCad version:** `10.0.4`  
**KiCad range:** `10.0.x`

## Summary

| Check | Status |
|---|---|
| KiCad CLI found | PASS |
| KiCad version matches `10.0.x` | PASS |
| Canary command completed | PASS |
| Failing fixtures | none |
| Step results | 31 PASS |
| Intentional optional skip | 1 (`allegro-import-capability`) |
| Manufacturing export feature gate | enabled |
| Evidence summary archived | PASS |

The optional Allegro import probe is recorded as a non-failing skip because the
current KiCad 10.0.4 `kicad-cli pcb import --help` output does not advertise the
optional `allegro` token. Required PADS import capability is present and passed.

## Command

The canary was run as a non-root `kicadcanary` user so the read-only output test
exercises real filesystem permissions instead of root bypass behavior:

```bash
.venv/bin/python scripts/kicad_canary.py run \
  --artifacts /tmp/kicad-canary-artifacts/kicad-10-0-4-2026-07-03 \
  --kicad-range 10.0.x
```

The run completed with:

```text
KiCad canary passed for 10.0.x; artifacts written to /tmp/kicad-canary-artifacts/kicad-10-0-4-2026-07-03.
```

## Archived Evidence

| File | Purpose |
|---|---|
| `docs/evidence/kicad-10-0-4/2026-07-03/summary.json` | Normalized canary pass summary, environment, command, step counts, covered surface, and generated bundle hash. |
| `docs/evidence/kicad-10-0-4/2026-07-03/failing-fixtures.txt` | Empty failing fixture list from the passing run. |

The generated artifact bundle was 129,071 bytes with SHA-256
`d5d918932713ab9aad09626670caf1690ab84f5a7cd1b133fcd7c66f11f74057`. The
bundle was generated from the same command above and can be recreated from the
checked-in source and fixture set.

## Covered Surface

The 2026-07-03 run covered the current required KiCad 10.0.4 CLI evidence set:

- KiCad version detection.
- Clean and dirty ERC JSON output.
- Clean and dirty DRC JSON output.
- Schematic PDF export.
- Schematic PDF export with property-popup suppression.
- PCB PDF, SVG, and DXF export.
- BOM and KiCad S-expression netlist export.
- Board statistics export.
- PADS import capability probe.
- Optional Allegro import capability probe.
- STEP, STEPZ, BREP, GLB, STL, and render exports.
- Gerber, drill, and IPC-2581 manufacturing exports.
- Schematic DXF, SVG, Python BOM, and SPICE netlist exports.
- Path-with-spaces, Unicode path, and read-only output behavior.

## Release Gate Interpretation

This canary evidence satisfies issue #271 for the 3.17.x release line: the
current primary KiCad baseline is verified against KiCad CLI `10.0.4`, and the
result evidence is archived in-repo. Future release lines should refresh this
directory with a new date-stamped evidence folder rather than mutating this
historical record.

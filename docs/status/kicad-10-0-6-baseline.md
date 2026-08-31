# KiCad 10.0.6 Baseline

**Reviewed:** 2026-08-31

KiCad MCP Pro treats KiCad 10.0.6 as the current primary KiCad 10 stable
baseline. The repository compatibility matrix records this in
`kicad.latestVerified` and `kicad10FeatureParity.baseline`.

## Release Impact

KiCad 10.0.6 was released on 2026-08-29 as a 10.0-series bugfix release. The
`kicad/kicad-10.0-releases` PPA now serves 10.0.6 exclusively; the prior
10.0.5 package is no longer installable from it, which is why this promotion
was required rather than optional. The MCP surface most at risk from patch
drift remains the headless CLI path: ERC/DRC JSON reports, PCB export
artifacts, importer capability help text, and manufacturing release formats.
The 10.0.6 changelog documents Allegro-import bug fixes (reference-field
collision avoidance, netlist room-name sanitization) on the GUI import path;
it does not claim new `kicad-cli pcb import --format allegro` CLI support, so
the Allegro CLI import surface remains `blocked` pending fresh capability-probe
evidence from the required canary.

## Notable 10.0.6 Changes Relevant to This Product

Full changelog reviewed against the current tool surface. Most entries are
upstream-only fixes this product inherits automatically through `kicad-cli`
with no code change required; a few are worth recording explicitly:

- **CLI: "Used per-variant field values in multi-variant BOM export" (#24936).**
  Directly affects `export/bom.py`'s `--variant` handling behind
  `export_bom()`. Previously-incorrect multi-variant BOM field values are now
  fixed upstream; no code change needed here, but the required canary's
  variant-BOM coverage is the verification point for this fix on the actual
  10.0.6 CLI.
- **PCB Editor: three Specctra DSN export fixes** (double-quoted field
  escaping #24946, duplicate/empty footprint references #24947, layer-name
  quoting #24948). Directly improves `route_export_dsn()`
  (`tools/routing.py`) output correctness for FreeRouting hand-off — no code
  change needed, this is a pure quality improvement inherited from the CLI.
- **PCB Editor / 3D Viewer: IPC-2581 export fixes**, including a crash fix for
  boards with no outline and new "Report warnings on IPC-2581 export"
  (#25149, several sub-fixes). Relevant to `export_ipc2581`. The crash fix is
  a straightforward robustness win. The new warning-reporting behavior
  surfaced a pre-existing gap: `export/pcb_manufacturing_outputs.py` only
  reads `stderr` on a non-zero exit code, so any new warnings the CLI emits
  on a *successful* export are currently discarded rather than shown to the
  caller. Tracked as a follow-up, not fixed in this baseline-promotion
  change to keep it focused.
- **PCB Editor: Gerber X3 DNP/BOM-exclude honoring (#25010)** and **drill
  report back-drilled hole counting + back-drill filename layer fix (#25021,
  #23452).** Improve `export_gerber()`/`export_drill()` output correctness
  automatically; no code change needed.
- **IPC API: expanded stackup parameters (#24182)**, plus a new `parent`
  field on board types and a new flip-board-item command. Potentially
  relevant to `pcb_get_stackup`/`pcb_set_stackup` and the native-live
  transaction surface (`pcb/transaction_lifecycle.py`), but these are new
  upstream capabilities, not fixes to existing behavior — evaluating whether
  to consume them is a separate, deliberate feature decision, not part of
  this baseline promotion.

## Required Canary Evidence

`scripts/kicad_canary.py` is the required 10.0.6 drift gate. The primary lane
fails when the installed CLI does not match the configured `10.0.x` range or
when any required artifact is missing.

The 10.0.6 canary covers:

- ERC JSON and DRC JSON reports for clean and violation fixtures.
- Gerber, drill, IPC-2581, STEP, PDF/SVG/DXF, BOM, netlist, and board-stat
  artifacts.
- Importer capability probes for PADS and Allegro.
- Path-with-spaces, Unicode path, and read-only output handling.

## Carried-Forward Fixture

The `kicad-10-0-3-regressions` fixture remains intentionally named for its
original patch release. It is a regression corpus carried forward under the
10.0.6 baseline, not a statement that the primary tested KiCad version is still
10.0.3.

## Platform Verification Status

The required Ubuntu canary installs the final `10.0.6` package from the stable
KiCad 10.0 PPA and rejects any other patch version. Windows remains represented
by the required `10.0.6` canary lane; final physical-host evidence is tracked in
[issue #427](https://github.com/oaslananka/kicad-mcp-pro/issues/427).

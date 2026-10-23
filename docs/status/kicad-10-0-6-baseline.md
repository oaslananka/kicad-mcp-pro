# KiCad 10.0.6 Baseline

> **Historical 10.0.6 compatibility checkpoint.** Since 2026-10-23,
> the globally verified supported-surface patch is **10.0.7**, as documented
> in [its separately reviewed feature-parity baseline](../compatibility/kicad-10-0-7-feature-parity.md).
> This historical evidence and the Ubuntu 22.04 / 10.0.6 legacy canary remain
> intact; statements below describe the historical 10.0.6 checkpoint.

**Reviewed:** 2026-09-04

KiCad MCP Pro treats KiCad 10.0.6 as the **last verified compatible**
KiCad 10 baseline, not the newest upstream stable patch. The repository
compatibility matrix records this tested baseline in `kicad.latestVerified`
and `kicad10FeatureParity.baseline`.

**Upstream status as of 2026-10-09:** KiCad
[10.0.7 stable](https://www.kicad.org/blog/2026/10/KiCad-10.0.7-Release/)
was released on 2026-10-07. It is **not yet promoted** by this project.
A compatibility promotion requires successful version-pinned native canaries
covering ERC/DRC, BOM/netlist and manufacturing exports, PCM/IPC and applicable
platform regressions. Do not change `latestVerified` based only on the
upstream release announcement.

## Legacy Ubuntu 22.04 exception and candidate 10.0.7 evidence

The `ubuntu-22.04` jobs in `.github/workflows/kicad-live-e2e.yml` and
`.github/workflows/dev-bootstrap.yml` still explicitly require `10.0.6`.
This is a **legacy platform exception**, not an assertion that Ubuntu 22.04
has passed the 10.0.7 qualification. A tested attempt to build the official
10.0.7 Jammy PPA encountered a libgit2 `git_packbuilder_name` compatibility
blocker; do not silently remove these jobs or relax their exact-version tests.
The separately qualified Ubuntu 24.04 10.0.7 lane is not interchangeable
with Ubuntu 22.04. See the [10.0.7 patch parity and platform audit](../evidence/kicad-10-0-7/2026-10-12-feature-parity-audit.md).

On hosted Windows, the signed fixed-SHA-256 official 10.0.7 installer has
been exercised by an [automatic main-push native run](https://github.com/oaslananka/kicad-mcp-pro/actions/runs/38176395461)
(32/32 native steps, 5/5 semantic comparisons); the [community Chocolatey
KiCad package](https://community.chocolatey.org/packages/kicad) was listed at
10.0.6 on 2026-10-12. The new Windows runner is an **extra post-merge and
weekly signal**, not a new required PR context or a general version promotion.
The real Windows GUI/IPC qualification remains explicitly operator-dispatched.

## Release Impact

KiCad 10.0.6 was released on 2026-08-29 as a 10.0-series bugfix release. At that review, the
`kicad/kicad-10.0-releases` PPA served 10.0.6 exclusively; the prior
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
  fixed upstream. A 2026-09-04 probe against KiCad's upstream 10.0.6 QA
  variant fixture confirmed `R1=10K_V1` for `Variant 1` and `R1=10K_V2` for
  `Variant2` on the installed 10.0.6 CLI. The repository canary currently
  checks generic BOM export but does not assert these variant-specific values;
  dedicated hermetic semantic coverage is tracked in
  [#843](https://github.com/oaslananka/kicad-mcp-pro/issues/843).
- **PCB Editor: three Specctra DSN export fixes** (double-quoted field
  escaping #24946, duplicate/empty footprint references #24947, layer-name
  quoting #24948). Directly improves `route_export_dsn()`
  (`tools/routing.py`) output correctness for FreeRouting hand-off — no code
  change needed, this is a pure quality improvement inherited from the CLI.
- **PCB Editor / 3D Viewer: IPC-2581 export fixes**, including a crash fix for
  boards with no outline and new "Report warnings on IPC-2581 export"
  (#25149, several sub-fixes). Relevant to `export_ipc2581`. The product now
  preserves successful-export diagnostics from KiCad 10.0.6 and surfaces
  them to the caller under a `Warnings:` section instead of silently
  discarding `stderr`.
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

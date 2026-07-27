# KiCad 10.0.5 Baseline

**Reviewed:** 2026-07-27

KiCad MCP Pro treats KiCad 10.0.5 as the current primary KiCad 10 stable
baseline. The repository compatibility matrix records this in
`kicad.latestVerified` and `kicad10FeatureParity.baseline`.

## Release Impact

KiCad 10.0.5 was released on 2026-07-22 as a 10.0-series bugfix release. The MCP surface most
at risk from patch drift remains the headless CLI path: ERC/DRC JSON reports,
PCB export artifacts, importer capability help text, and manufacturing release
formats.

## Required Canary Evidence

`scripts/kicad_canary.py` is the required 10.0.5 drift gate. The primary lane
fails when the installed CLI does not match the configured `10.0.x` range or
when any required artifact is missing.

The 10.0.5 canary covers:

- ERC JSON and DRC JSON reports for clean and violation fixtures.
- Gerber, drill, IPC-2581, STEP, PDF/SVG/DXF, BOM, netlist, and board-stat
  artifacts.
- Importer capability probes for PADS and Allegro.
- Path-with-spaces, Unicode path, and read-only output handling.

## Carried-Forward Fixture

The `kicad-10-0-3-regressions` fixture remains intentionally named for its
original patch release. It is a regression corpus carried forward under the
10.0.5 baseline, not a statement that the primary tested KiCad version is still
10.0.3.

## Platform Verification Status

The required Ubuntu canary installs the final `10.0.5` package from the stable
KiCad 10.0 PPA and rejects any other patch version. The GitHub-hosted Windows
package and MCP server matrices also pass on the 10.0.5 baseline.

Physical-host verification was completed on 2026-07-27 using the AMD2700X
Windows 11 workstation. The released 3.29.0 source passed all 31 stable canary
entries, and the default KiCad IPC discovery connected to an active KiCad
10.0.5 PCB Editor session with a live board open. See the sanitized
[physical Windows evidence](../evidence/kicad-10-0-5/2026-07-27/amd2700x-windows.md).

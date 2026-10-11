# KiCad 10.0.7 patch-specific feature-parity audit (bounded)

**Reviewed:** 2026-10-12 · **Issue:** [#1181](https://github.com/oaslananka/kicad-mcp-pro/issues/1181) · **Decision:** `bounded-not-promoted`.

This is a *candidate patch audit*, not a replacement for
[`kicad10FeatureParity.baseline: 10.0.6`](../../compatibility/kicad-10-0-6-feature-parity.md)
or `kicad.latestVerified: 10.0.6`. The patch delta is indexed in
`compatibility.yaml` under `kicad10FeatureParity.candidatePatchReview`.
Do **not** infer full feature-level equivalence from a passing general canary,
or treat a known-invalid reference board as a successful manufacturing run.

## Bounded evidence that has passed

| Surface | Verified assertion | Evidence boundary |
| --- | --- | --- |
| Windows 2025 native, exact merged `main` | **32/32** CLI operations and **5/5** semantic differentials; fail-closed installer SHA-256 and Authenticode | [First true automatic `push` run #38176395461](https://github.com/oaslananka/kicad-mcp-pro/actions/runs/38176395461), source `6b4474d1c02889a61e16a1eedccd9e6973d63056` |
| Ubuntu 24.04 x64 native | **32/32** and **5/5** on real KiCad 10.0.7 | [Prior pinned evidence](2026-10-11-main-qualification.md), source `ee60c037a25187b6d2487b45d085781c6986f25b`; **not Jammy** |
| macOS 15 native and GUI/IPC | **32/32**, **5/5**, real editor **2/2** | [Run #38170872908](https://github.com/oaslananka/kicad-mcp-pro/actions/runs/38170872908); prior tested source, not the latest merged `main` |
| Windows 2025 GUI/IPC | Real editor **2/2** | [Manual run #38174350209](https://github.com/oaslananka/kicad-mcp-pro/actions/runs/38174350209), source `14224f81e6322ee0175a8596b05a892747ef0c56`; not an automatic GUI job |

These checks qualify the *tested commands, fixtures, versions and source commits*.
They do not assert every KiCad 10.0.7 patch-specific bugfix, every GUI workflow,
or PCB electrical/manufacturing success. The pre-existing 10.0.6 feature matrix
still contains deliberately `partial`, `blocked`, and `not-applicable` surfaces.

## New upstream patch deltas requiring targeted regressions

The upstream [10.0.7 release notes](https://www.kicad.org/blog/2026/10/KiCad-10.0.7-Release/)
list these changes. `targeted-evidence-pending` means the existing general
canary/GUI smoke **does not establish that exact fix's semantic behavior**;
it does not allege a KiCad defect or a regression in this product.

| Gap id | Upstream change | Current evidence | Targeted acceptance still needed |
| --- | --- | --- | --- |
| `erc-json-unit-scale` | ERC JSON report unit-scale fix ([#25582](https://gitlab.com/kicad/code/kicad/-/work_items/25582)) | Native canary confirms ERC JSON generation and negative exit-code behavior | Compare known coordinate/unit magnitudes and serialized ERC JSON against a versioned fixture; avoid relying on localized report wording |
| `multi-root-schematic-plot` | Plot every top-level sheet of a multi-root schematic ([#25198](https://gitlab.com/kicad/code/kicad/-/work_items/25198)) | General schematic PDF export exists | A multi-root fixture asserting expected sheet/page identities, counts and no missing output |
| `bom-project-output-filename` | Honor BOM output filename saved in project ([#24860](https://gitlab.com/kicad/code/kicad/-/work_items/24860)) | Generic BOM creation is exercised | Project-file configured output filename with no unexpected overwrite or path escape |
| `gerber-drill-marks` | Keep drill marks out of Gerber export ([#25532](https://gitlab.com/kicad/code/kicad/-/work_items/25532)) | Gerber + Excellon drill export existence checked | Geometry/content assertions that exclude unintended drill marks and preserve intended plated holes |
| `allegro-24-25-cli-capability` | Allegro 24.1/25.1 **PCB Editor** importer support and geometry fixes | Current Windows native canary explicitly skips unsupported CLI Allegro format | Inspect 10.0.7 `kicad-cli pcb import --help`; keep product CLI Allegro `blocked` until a tested CLI token exists; GUI format additions are not CLI API proof |
| `ipc-expanded-object-contracts` | KiCad 10.0.7 IPC board table, variants, zone override and other object handling additions | Actual GUI/IPC smoke uses a bounded subset of four live MCP tools | Focused read/write/roundtrip/negative capability probes for newly used IPC objects before declaring parity |

**Status of all six patch-specific rows:** `targeted-evidence-pending`.
This is a review queue, not an invented failure list. Base 10.0.6 statuses and
unaffected KiCad 11 preview contracts are not rewritten.

## Platform exception, packaging and promotion gates

- **Ubuntu 22.04 (`jammy`) remains exactly `10.0.6`:** both the
  `kicad-live-e2e.yml` and `dev-bootstrap.yml` canary jobs use `ubuntu-22.04`
  and require `kicad-cli version` to equal `10.0.6`. An attempted KiCad 10.0.7
  Jammy PPA build was blocked by the observed libgit2 `git_packbuilder_name`
  issue. This is a documented, isolated **legacy CI exception**, not permission
  to skip native tests or a claim of successful Jammy 10.0.7 support.
- **Ubuntu 24.04 (`noble`) 10.0.7** remains separately qualified; it must not
  be used as evidence to waive a Jammy-specific requirement.
- **Windows:** the [Chocolatey community KiCad package](https://community.chocolatey.org/packages/kicad)
  was still **10.0.6** on review. The SHA-256 pinned official installer is
  already successful under a selective `main`-push and weekly native canary,
  but **not** a new required PR gate; the live GUI/IPC workflow remains manual.
- **Feature parity:** these six targeted semantic patch probes must be
  resolved or explicitly risk-reviewed before moving `kicad10FeatureParity.baseline`.
  General native 32/32 and semantic 5/5 do not automatically cover them.
- **Product support and manufacturing:** `kicad.latestVerified` remains
  `10.0.6`. The real-agent-authored manufacturing reference-board benchmark
  tracked in [#729](https://github.com/oaslananka/kicad-mcp-pro/issues/729) and
  [#730](https://github.com/oaslananka/kicad-mcp-pro/issues/730) remains
  independently unqualified. Do not declare a fully verified fabrication
  result, publish a release or close #1181 based on this document.

**Next accepted work:** add bounded numeric ERC JSON and multi-root PDF
regression fixtures first, then BOM/Gerber content and IPC-specific probes;
revisit the exact CI/platform contract only after source-bound evidence lands.

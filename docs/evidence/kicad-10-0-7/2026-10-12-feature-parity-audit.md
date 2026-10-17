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

## macOS DMG supply-chain digest pin (qualification infrastructure)

The opt-in `.github/workflows/kicad-10-0-7-macos-gui-ipc-qualification.yml`
previously required a valid KiCad Apple app code signature, exact CLI
version and native GUI/IPC tests, but it only **recorded** the DMG SHA-256
**after** mounting. A new workflow guard compares the downloaded official
universal **10.0.7** DMG SHA-256 against
`fbc27419b841a9a2a8b143b5875a87b8bd943ffcf487d53c78a8fb6d24c59e27`
**before** calling `hdiutil attach`; any mismatched CERN/MIT mirror content
now fails closed without mounting or executing it. The digest comes from
the source-bound, signed [2026-10-11 macOS native evidence](2026-10-11-macos-10-0-7-signed-native-gui-ipc.json)
and was **independently rechecked** against the bounded artifact of successful
[macOS run #38170872908](https://github.com/oaslananka/kicad-mcp-pro/actions/runs/38170872908).
The same attested digest is carried into the sanitized provenance summary.

This hardens the **already manually dispatched native PCB Editor GUI/IPC**
qualification lane; it does **not** run automatically for PRs, change the
KiCad 10.0.6 compatibility baselines, or prove the missing Windows/macOS
**Schematic Editor BOM** user-interface contract. The new exact-head hosted
macOS execution and artifact verdict, when available, must be recorded as
separate evidence; workflow static review alone does not establish a tested
native run.

## Exact merged-source physical Linux patch regressions (2026-10-12)

On **Ubuntu 24.04.5 x86_64 with native KiCad CLI 10.0.7**, the *actual*
three isolated read-only regression probes ran against clean canonical
`main@8e31947f9e136ea1e33d07e89d9cd599a3263592`. The versioned bounded
[JSON evidence](2026-10-12-main-linux-targeted-patch-regressions.json)
includes exact source revision, four source fixture SHA-256 digests, observed
native measurements and explicit unsupported scopes. The source repo was
**clean after execution**; native project copies, PDFs, Gerbers, drills,
ERC reports and temporary pypdf installation were deleted.

| Upstream patch | Exact observed result on **this Linux host** | Qualification boundary |
| --- | --- | --- |
| ERC JSON coordinate scale #25582 | **PASS** for `mm`, `in`, `mils`: J1 (15,14) mm, unit-scaled positions and **4** expected diagnostics each | Native CLI format semantics only; not GUI or other hosts |
| Flat top-level multi-root PDF #25198 | **PASS**: **2 PDF pages**, one for `FlatRoot2` / `clean-led-kicad10`, one for `FlatRoot1` / `erc-power-pin-error`; order not assumed | Exact fixture/title and page count; not arbitrary hierarchy |
| NPTH Gerber drill marks #25532 | **PASS**: full drill style selected; **0** NPTH F.Cu flashes, **1** PTH positive-control flash, 3.2-mm NPTH hole preserved at (50,50) mm in Excellon | Saved board-settings CLI and drill intent; not Windows editor Python plot API |

These three targeted **Linux CLI** subgates are now verified on this exact
source; they were previously merely candidate scripts. This **does not**
complete all six upstream patch deltas, support-platform qualification,
Windows/macOS *Schematic Editor* BOM GUI, stable expanded IPC bindings or
manufacturing. `latestVerified` and the parity baseline remain **10.0.6**.

## Exact merged-source signed Windows native patch regressions (2026-10-12)

The **manual** [Windows 2025 native workflow run #38199126080](https://github.com/oaslananka/kicad-mcp-pro/actions/runs/38199126080)
ran on protected `main@5d5324b1c90d65eebec545d7f83c455b05b6042b`.
The official **10.0.7** installer was verified against the previously
reviewed SHA-256 **before execution** and had valid KiCad Authenticode.
The job finished **SUCCESS**; an independent download of artifact
`kicad-10-0-7-windows-native` (artifact ID `11724038722`) was checked for
its exact source revision, installer SHA/signature, **32/32 native canary**
steps, **5/5 semantic differentials** and **all three** patch-specific
regressions. No failing fixtures or false PASS/FAIL/divergence were observed.
The source-bound [bounded Windows JSON record](2026-10-12-main-windows-targeted-patch-regressions.json)
preserves the five raw report SHA-256 digests, not the reports, free-form logs,
or local file paths. The downloaded report workspace was deleted after review.

| Upstream patch | **Real Windows 2025 KiCad 10.0.7 CLI** result | Difference from prior Linux check |
| --- | --- | --- |
| ERC JSON scaling #25582 | **PASS** J1 (15,14) mm with correct `mm`, `in`, `mils` values; **5** diagnoses per unit | Linux source-bound CLI probe recorded **4** per unit; unit conversions and within-host counts remain consistent |
| Flat two-root PDF #25198 | **PASS**, both named roots; 2 pages | Windows rendered FlatRoot1 then FlatRoot2; Linux rendered the reverse; test deliberately requires identities, not ordering |
| NPTH full drill marks #25532 | **PASS**, **0** NPTH F.Cu flashes and **1** plated control flash; Excellon retains 3.2-mm NPTH at (50,50) mm | Same measurable geometry on Linux; Windows **PCB Editor Python API** mode was not separately tested |

This adds **actual Windows native CLI platform evidence**, not a native
Windows/macOS **Schematic Editor BOM GUI** test, signed macOS BOM field
verification, unavailable expanded IPC bindings or manufactured-board success.
`kicad.latestVerified` and feature-parity baseline remain **10.0.6**.
The different ERC diagnostic counts are recorded, **not** silently
reconciled or generalized to other schematics.

## New upstream patch deltas requiring targeted regressions

The upstream [10.0.7 release notes](https://www.kicad.org/blog/2026/10/KiCad-10.0.7-Release/)
list these changes. `targeted-evidence-pending` means the existing general
canary/GUI smoke **does not establish that exact fix's semantic behavior**;
it does not allege a KiCad defect or a regression in this product.

| Gap id | Upstream change | Current evidence | Targeted acceptance still needed |
| --- | --- | --- | --- |
| `erc-json-unit-scale` | ERC JSON report unit-scale fix ([#25582](https://gitlab.com/kicad/code/kicad/-/work_items/25582)) | Native canary confirms ERC JSON generation and negative exit-code behavior | Compare known coordinate/unit magnitudes and serialized ERC JSON against a versioned fixture; avoid relying on localized report wording |
| `multi-root-schematic-plot` | Plot every top-level sheet of a multi-root schematic ([#25198](https://gitlab.com/kicad/code/kicad/-/work_items/25198)) | General schematic PDF export exists | A multi-root fixture asserting expected sheet/page identities, counts and no missing output |
| `bom-project-output-filename` | Honor BOM output filename saved in project ([#24860](https://gitlab.com/kicad/code/kicad/-/work_items/24860)) | Native Linux **10.0.7** operator GUI/Xvfb fixture passed: saved output field, edit→Cancel, reopen-original, unchanged file SHA-256 (see below) | Independent Windows/macOS real GUI reruns before cross-platform acceptance; CLI BOM creation is not proof |
| `gerber-drill-marks` | Keep drill marks out of Gerber export ([#25532](https://gitlab.com/kicad/code/kicad/-/work_items/25532)) | Gerber + Excellon drill export existence checked | Geometry/content assertions that exclude unintended drill marks and preserve intended plated holes |
| `allegro-24-25-cli-capability` | Allegro 24.1/25.1 **PCB Editor** importer support and geometry fixes | Current Windows native canary explicitly skips unsupported CLI Allegro format | Inspect 10.0.7 `kicad-cli pcb import --help`; keep product CLI Allegro `blocked` until a tested CLI token exists; GUI format additions are not CLI API proof |
| `ipc-expanded-object-contracts` | KiCad 10.0.7 IPC board table, variants, zone override and other object handling additions | Actual GUI/IPC smoke uses a bounded subset of four live MCP tools | Focused read/write/roundtrip/negative capability probes for newly used IPC objects before declaring parity |

### Reproducible ERC JSON unit-scale acceptance candidate (#25582)

`scripts/kicad_107_erc_units.py` implements a fail-closed, **exact 10.0.7**
native CLI probe on an isolated *copy* of the maintained
`erc-power-pin-error` fixture. It requires native `--exit-code-violations`
exit code **5** for each `mm`, `in` and `mils` report; the unique non-zero J1
`footprint_link_issues` location must be **(15, 14) mm**, **(15/25.4,
14/25.4) in**, and **(15000/25.4, 14000/25.4) mils**, within a fixed
numeric tolerance. It also compares diagnostic counts, metadata units, and
installed CLI version. It emits only a sanitized coordinate/count JSON
summary, not raw local filenames or native error text.

This test is integrated into the signed, fixed-SHA-256 **Windows 2025 native
10.0.7** post-merge/weekly workflow, alongside the existing 32/32 CLI and
5/5 semantic gates. Standalone physical KiCad 10.0.7 execution is required
before the pull request is merged; exact-head Windows runner success and
artifact verification must be recorded separately. The probe's introduction
**does not itself satisfy** the cross-platform/promotion criterion or change
the six-row targeted evidence queue. The Ubuntu 22.04 **10.0.6** legacy lane
and manually dispatched GUI/IPC workflow are not changed.

### Native flat multi-root PDF candidate acceptance (#25198)

`scripts/kicad_107_flat_root_pdf.py` creates a disposable KiCad 10.0.7
project from **two independent existing in-repository schematic fixtures**.
The script adds distinct top-level root UUIDs, and writes the actual project
`schematic.top_level_sheets` records (filename, name and UUID), plus their
`sheets` identity mapping. Neither schematic is a hierarchical child; the
source fixtures themselves remain untouched. An unrelated hierarchical
multi-sheet fixture would not exercise upstream #25198.

The CLI is **exact-version gated at 10.0.7** and run via the existing native
canary executor. Exporting the first root must create a parseable PDF with
**exactly two pages**, one containing each corresponding named root **and** its
unique schematic title; missing, repeated, ambiguous or mismatched identities
are errors. Page sequence is not assumed: on an observed physical Linux 10.0.7
run the output order was the reverse of the project manifest. The native PDF
and temporary project are deleted; only two page names/titles and a source
revision are persisted as bounded JSON evidence.

The project locks **pypdf 6.20.0** (BSD-3-Clause) as a dev-only dependency for
cross-platform PDF page-text assertions. This is a narrowly scoped native
regression integrated into the existing SHA-256/Authenticode-verified Windows
10.0.7 post-merge and weekly workflow, **not** a fork PR installer trigger or
a new branch-protection required context. Hosted Windows exact-source execution
and artifact validation remain separate acceptance gates before this gap is
classified as validated outside the physical Linux proof. Global version
promotion and independent GUI/IPC acceptance are still out of scope.

### Expanded KiCad 10.0.7 IPC binding availability (not GUI parity)

Upstream's [official `kicad-python` Board reference](https://docs.kicad.org/kicad-python/board.html)
marks new board **tables**, **reference points**, **embedded files** and
related wrappers as **Added in 0.9.0 (KiCad 10.0.7)**. However, as of
2026-10-12, the latest stable [published PyPI package](https://pypi.org/project/kicad-python/)
is **0.8.0**, while this repository intentionally locks **0.7.1** under
`kicad-python>=0.6,<0.8`. A native KiCad 10.0.7 binary does not itself
supply the missing Python wrapper methods.

`scripts/kicad_107_ipc_binding_gate.py` performs a **read-only**, offline
installed-binding audit; it does not contact the IPC server, edit a board or
claim a KiCad GUI verdict. It requires a stable published binding at least
**0.9.0**, checks five documented methods on `kipy.board.Board` and three
corresponding wrapper classes. Missing package, prerelease version, missing
method or missing type all produce a bounded JSON `status: blocked`.
`--require-ready` exits nonzero in that case; the default audit mode exits
successfully after reporting the blocked state so maintained 0.7.1 CI is not
mistakenly failed for an unshipped upstream feature:

```bash
uv run --frozen python scripts/kicad_107_ipc_binding_gate.py
uv run --frozen python scripts/kicad_107_ipc_binding_gate.py --require-ready
```

Even a future `binding-ready-only` result keeps `nativeGuiQualified: false`
until **independent native GUI IPC read/write/negative cases on versioned
board fixtures** pass. This is an availability precondition, **not** a
supported-version promotion, headless IPC substitute, upstream defect claim,
or authorization to bypass read-only/manual manufacturing controls.

### Portable operator-only Windows/macOS Schematic Editor BOM fixture (NOT qualified)

KiCad 10.0.7's upstream [BOM regression #24860](https://gitlab.com/kicad/code/kicad/-/work_items/24860)
is explicitly a **Schematic Editor GUI** problem, not a CLI BOM export
problem. The pre-existing Windows/macOS `workflow_dispatch` GUI/IPC smoke
runs **PCB Editor** and does not exercise this field, so neither platform is
qualified for the BOM fix by those passing jobs.

`scripts/kicad_107_bom_portable.py` provides **cross-platform, dependency-free
preparation and post-observation integrity checks** for two *brand-new*,
non-hierarchical, valid native KiCad 10.0.7 schematic/project pairs generated
under a **fresh cryptographically random session ID in the operating
system’s temporary directory**. The CLI does **not accept an arbitrary file
path** for project creation or verification; its session identifier is a
strict 32-character lowercase hexadecimal token. No user project, global
settings or GUI is opened, overwritten or cleaned by the script. Different projects A and B have
different saved `schematic.bom_export_filename` values, so a stale filename
leaking between projects is detectable. This small empty-sheet fixture was
opened on **real Linux 10.0.7 Project Manager + Schematic Editor + Symbol
Fields Table** in an isolated Xvfb profile as a structural preflight; it does
**not** constitute Windows/macOS GUI qualification.

An operator using an **isolated disposable Windows/macOS GUI account/profile**
with a verified native 10.0.7 installation may run:

```bash
python scripts/kicad_107_bom_portable.py prepare
python scripts/kicad_107_bom_portable.py locate --session HEX_SESSION_FROM_PREPARE
# After first native Project Manager open/close of BOTH disposable projects:
python scripts/kicad_107_bom_portable.py baseline --session HEX_SESSION_FROM_PREPARE
# After independent BOM GUI field/Cancel observations:
python scripts/kicad_107_bom_portable.py verify --session HEX_SESSION_FROM_PREPARE
```

**Required initialization boundary:** KiCad's first native Project Manager
exit can expand the minimal `.kicad_pro` into full defaults. Real Windows
10.0.7.51283 reproduced this: both project hashes changed, but the BOM
filename and schematic hashes were preserved; the expanded project was
byte-identical on the next manager open/close.

Before the actual BOM-dialog observations, open and close **each** disposable
project once in the **same isolated native KiCad profile**, without exporting
or editing. Close both managers, then run `baseline --session
HEX_SESSION_FROM_PREPARE` exactly once. It requires KiCad's full project
shape, unchanged schematic bytes and stored BOM names, and no unexpected
keys, CSV outputs or symlinks. This explicitly seals the **post-initialization,
pre-BOM-test** project hashes. It rejects an uninitialized project and
refuses a second baseline. Never re-arm after starting BOM GUI observations:
post-test `verify` compares project bytes strictly with this reference.
The manifest is operator-mutable, not tamper-proof provenance. Baseline
arming itself is **not** a BOM GUI acceptance result.

Run with a native Python 3.13+ interpreter on Windows/macOS. `prepare`
prints an opaque `sessionId`; `locate` prints the absolute **local** OS-temp
workspace path for the operator to open, and neither command is a public CI
artifact. The workspace is new and the script refuses collisions. Inspect
`manifest.json` for the two unique stored BOM output filename sentinels,
then manually, on a **trusted interactive desktop**:

1. Open `PortableBom107A.kicad_pro` **through KiCad Project Manager**, open
   Schematic Editor, choose **Tools → Generate Bill of Materials** (or the
   Symbol Fields Table icon), select **Export**, and record the exact **Output
   file** value. Click **Cancel**, not Export, then fully close that KiCad
   session; do not proceed past unknown windows, permission prompts or terms.
2. Under the **same isolated GUI profile**, open independent project B via
   its `.kicad_pro`, inspect Export's output field. It must contain project
   **B's** unique saved value, never A's. Change the field to
   `BOM_CANCEL_NOT_PERSISTED_107.csv`; click **Cancel** without saving or
   exporting, then reopen the same dialog and record the restored output
   field value (B's original). Close KiCad cleanly.
3. Run `verify` again. It checks SHA-256 of both initialized
   `.kicad_pro` baselines and original `.kicad_sch` files against the
   saved manifest and refuses any
   unexpected `.csv` output, symlinks or malformed project identities. A
   machine-readable result `integrity-pass` **does not prove that the GUI was
   used**. With *independently witnessed* exact field readings, optionally
   submit `--observed-a NAME_A --observed-b NAME_B --reopened-b NAME_B
   --cancelled-b`; the result is **operator-attested**, not automated proof.

An untrusted party capable of editing both the project and `manifest.json`
can fabricate matching digests; this checks accidental file changes, **not
signed provenance**. Neither `integrity-pass` nor `operator-attested` ever
reports `nativeGuiQualified=true`. Windows/macOS BOM GUI status stays
**unverified** until a reviewer independently validates native session,
correct window and fields, exact KiCad build, Cancel semantics and source
integrity. This helper is deliberately **not** called by automatic CI or
underlying release/manufacturing workflows and does not change 10.0.6 pins.

### BOM GUI persisted filename and Cancel acceptance (#24860) — physical Linux 10.0.7

An **operator-only Xvfb-backed real KiCad Project Manager + Schematic Editor**
qualification confirmed the [upstream #24860](https://gitlab.com/kicad/code/kicad/-/work_items/24860)
GUI behavior on a locally installed native KiCad **10.0.7**. This is **not**
a `kicad-cli sch export bom` inference. The upstream report covers two distinct
contracts: read the project's persisted `schematic.bom_export_filename` into
the **Symbol Fields Table → Export → Output file** field, and discard a user
edit when clicking **Cancel**, without mutating the project file.

A reproducible, deliberately **manual-only Linux Xvfb** test is stored in
`tests/gui/manual_kicad_107_bom_gui.sh`. On an operator workstation equipped
with the *official installed single-root demo*, KiCad 10.0.7, Xvfb, `xdotool`
and apt Python `wx`, run:

```bash
KICAD_BOM_GUI_OPERATOR=1 bash tests/gui/manual_kicad_107_bom_gui.sh
```

The script has **no user-project path argument**. It copies only the
installation-bundled single-root RoyalBlue54L NFC schematic/project into a
throwaway workspace, injects `BOM_STORED_PROJECT_107.csv` into a **copied**
`.kicad_pro`, and provisions private `HOME`, XDG settings, library tables and
software renderer for a fresh Xvfb 1440×900 session. No KiCad startup wizard,
telemetry permission, third-party browser terms or user configuration is
accepted or modified. Interaction **fails closed** if an unknown visible
window/modal appears. Raw screenshots, host paths, generated BOM files and
project copies are **not uploaded**; temporary workspace and display are
destroyed at completion.

The probe machine-reads the native wxWidgets text field through the isolated
Xvfb clipboard (not OCR), checks the **exact** stored filename, edits it to
`BOM_CANCEL_MUST_DISCARD_107.csv`, confirms the edit was actually applied,
clicks **Cancel**, requires the modal to close and the project SHA-256 to stay
**byte-identical**, then **reopens** the BOM Export dialog and requires the
*original* stored value rather than the cancelled edit. It cancels the reopened
dialog and checks the same SHA-256 again and confirms no BOM output was
written. An independently observed small-fixture manual trial produced all
these results at KiCad CLI/editor 10.0.7; the scripted run repeated them with
`status=pass` and all four flags `true`.

**Acceptance scope:** one genuine GUI session on one Linux native 10.0.7 host,
with explicit operator consent for a disposable test only. Not proof of
Windows/macOS GUI behavior or a stable, headless KiCad 10 IPC API. It adds **no**
automatic PR/`push`/release workflow, no installed package dependency and no
global feature-parity promotion. Keep BOM GUI portable-platform qualification
and independent GUI/IPC/manual gates in the #1181 review queue.

### Gerber NPTH drill-mark exclusion candidate acceptance (#25532)

`scripts/kicad_107_gerber_drill_marks.py` uses the already audited native
CLI runner and exact KiCad **10.0.7** version gate on two tiny *committed*
`.kicad_pcb` controls generated from the 10.0.7 `pcbnew` Python API:
`npth-stored-full-drill` has a single **non-plated 3.2-mm hole** at
(50, 50) mm; `pth-stored-full-drill` has one plated pad. **Both board
files explicitly persist `pcbplotparams (drillshape 2)`**, meaning full
drill marks were selected. With `pcb export gerbers --board-plot-params`,
the NPTH-only F.Cu file must have **zero Gerber `D03*` flash opcodes**,
while the PTH positive control must flash exactly **once**. This guards
against an accidentally empty or nonfunctional copper Gerber renderer.

The NPTH hole must remain in the independently generated *non-plated*
Excellon drill file with tool **3.2 mm** and expected drill XY position.
This distinguishes **suppression of false Gerber copper** from inadvertent
deletion of physical drill intent. All native Gerber/drill files and project
copies are isolated and deleted; the only uploaded artifact is bounded,
source-SHA-linked counts and known geometry (no customer PCB data).

A physical MSI KiCad **10.0.7** trial additionally executed the upstream
`pcbnew.PLOT_CONTROLLER` API on the NPTH sample with full drill marks and
observed zero F.Cu flashes. The portable automated Windows lane uses the
stored-settings CLI path; **this is not yet the complete plugin-specific GUI
or Python API qualification on Windows**. It remains a bounded native fix
regression for upstream #25532. GUI/IPC continues operator-dispatched and
no manufacturing success or global support promotion follows from this check.

**Six patch-specific rows remain in the global review queue**; the three
physical Linux CLI subgates above are **passed for that host and exact source**.
The remaining platform, GUI/editor, IPC and packaging acceptance is still
**pending**. Base 10.0.6 statuses and unaffected KiCad 11 preview contracts
are not rewritten.

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

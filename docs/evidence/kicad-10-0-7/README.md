# KiCad 10.0.7 — native CLI and real GUI/IPC platform evidence

Issue: [#1181](https://github.com/oaslananka/kicad-mcp-pro/issues/1181).
Linux source checkout: `c93559e47fc9dba2e0bdc11f64467f1ad1d0d6c1`.
Windows source checkout: `f5a498c71b9cb45cc52302e5ee98da39104b5c09`.
Recorded on 2026-10-10; OS/architecture: Linux x86_64. The original paired Linux and Windows reports covered native CLI/fixture
regressions only; **later, separate source-bound Windows, Ubuntu and macOS
real GUI/IPC evidence** is linked below. None of these results qualifies
autonomously engineered manufacturable reference boards.

The paired Linux machine-readable evidence file
[`2026-10-10-linux-native-canary.json`](2026-10-10-linux-native-canary.json)
preserves all 32 native canary step identities, expected-negative results and
return codes, skip state, output inventory, and five semantic differential
results for both versions. Native and custom hashes are included for every
differential. Machine-specific output paths and free-form command logs are
intentionally excluded; the underlying canary produces full local diagnostics
for independent reruns.

| Measured gate | 10.0.6 | 10.0.7 |
| --- | ---: | ---: |
| Canary steps with `ok=true` | 32/32 | 32/32 |
| Explicit skips | 1 | 1 |
| Failing fixture identities | 0 | 0 |
| Native/custom differential matches | 5/5 | 5/5 |
| False PASS, false FAIL, divergence | 0 | 0 |

The one explicit skip is the known unsupported Allegro CLI import. A canary
step with `ok=true` means that its expected semantics held; a negative test
can pass while its native process deliberately returns a nonzero status. The
DRC differential comparison uses *finding type/bucket/severity* rather than
human-readable short-net descriptions, which changed to `<no net>` in a
previous fixture comparison. Neither version passes clean-board electrical
design claims just because their native DRC failure buckets agree.

## Reproduce

Use this exact source revision, the project's locked uv 0.12.19 and Python
3.13.12 environment, and the official KiCad stable 10.0.7 Linux lite AppImage
archive listed with its SHA-256 in the JSON report. Independently verify
the downloaded archive/AppImage digests and extract the AppImage to an isolated
temporary location; do not overwrite the host KiCad installation.

For each version run the same native suite, selecting the appropriate
`kicad-cli` via `KICAD_CANARY_KICAD_CLI`:

```sh
uv sync --all-extras --frozen
KICAD_CANARY_KICAD_CLI=/path/to/version-specific/kicad-cli \
  uv run --all-extras python scripts/kicad_canary.py run \
  --artifacts artifacts/kicad-native-version \
  --kicad-range 10.0.x
```

Check `summary.json`, `failing-fixtures.txt` and
`differential/summary.json` in each run directory before comparing the
documented measurements.

The Linux evidence file records **download/integrity comparison evidence**,
not independent signature verification *at that time*. A later detached
AppImage minisign verification was documented separately in issue #1181.
The Linux-only snapshot did not qualify Windows. The independent Windows
10.0.7 native CLI qualification below is a later, separately source-bound
test; neither result qualifies GUI/IPC or complete agent-authored reference
boards.

## Windows 10.0.7 — signed installer and native CLI

The separate permanent
[`2026-10-10-windows-native-canary.json`](2026-10-10-windows-native-canary.json)
records the hosted Windows 2025 runner's exact
[successful manual workflow run #38022313667](https://github.com/oaslananka/kicad-mcp-pro/actions/runs/38022313667)
from protected main at `f5a498c71b9cb45cc52302e5ee98da39104b5c09`.
This is a **different source revision** than the Linux pair above.

| Measured Windows CLI gate | Result |
| --- | --- |
| Official 10.0.7 x64 installer Authenticode | Valid — KICAD SERVICES CORPORATION |
| Isolated Windows install + native CLI version | Passed — exact 10.0.7 |
| Native canary expected step statuses | 32/32 |
| Explicit capability/platform skips | 2 |
| Failing fixture identities | 0 |
| Native/custom semantic differentials | 5/5 matched |
| False PASS / false FAIL / divergence / infrastructure invalid | 0 / 0 / 0 / 0 |
| Temporary installer/install/config cleanup | Passed |

The two documented skipped steps were the unsupported Allegro import
capability and the read-only-output negative probe on Windows. Passing
negative DRC/ERC test steps can have intentional nonzero native exit codes.
The remaining differential projections cover connectivity, geometry, clean
and deliberately failing DRC, and manufacturing export inventory.

The JSON record preserves the exact installer SHA-256, signer certificate
subject/issuer, run and artifact IDs, original report SHA-256 digests,
the 32 result identities/statuses/exit codes, and both semantic result
hashes for all five comparisons. Paths are restricted to relative artifact
outputs; free-form logs and host paths are intentionally excluded. The
GitHub run artifact retains the complete original reports for **7 days**;
this committed summary remains after that retention window expires.

To reproduce on a disposable, separate Windows runner, manually dispatch
`.github/workflows/kicad-10-0-7-windows-qualification.yml` at the exact
recorded source revision. The workflow verifies the KiCad Authenticode
signature, installs into a temporary directory, checks native exit/version,
requires the bundled `share/kicad/symbols/Device.kicad_sym` library, and
binds the same isolated CLI and symbol libraries into the locked canary
runtime. Then inspect `summary.json` and
`differential/summary.json` for all required acceptance conditions.

**Qualification boundary:** Windows 10.0.7 native **CLI** compatibility
is demonstrated by this single source-bound canary, not Windows GUI/IPC,
native-editor interoperability, physical manufacturing, or autonomous
reference-board production. The currently tested Ubuntu stable CI lane
remains on KiCad 10.0.6. Do **not** promote
`compatibility.yaml`'s `kicad.latestVerified: 10.0.6` or issue a release
based solely on this Windows CLI evidence.

## Windows 10.0.7 — real PCB Editor GUI/IPC (2026-10-10)

In addition to the signed-installer CLI proof above, a separate
[hosted real Windows GUI/IPC qualification](2026-10-10-windows-10-0-7-real-gui-ipc.json)
ran on `windows-2025`, source
`e82432c81ba2ae31b04d2780c43971ac87aff7cb`,
[Actions run #38045310304](https://github.com/oaslananka/kicad-mcp-pro/actions/runs/38045310304).
The runner had a **user-interactive non-session-zero desktop** and
native KiCad version `10.0.7`. It passed **2/2 genuine GUI/IPC tests,
0 failures/skips**: structured file-backed fallback when the editor was
closed, then actual PCB Editor-backed live MCP reads and switching to
a distinct project. The bounded JSON copies the source runner's
schema/verdict/test identities and records its artifact ID and original
downloaded SHA-256. This real GUI result is independent of the
earlier native Windows 32/32 + 5/5 canary, and neither is a successful
autonomous board-production claim.

## Ubuntu 24.04 — signed stable PPA binary, native CLI (2026-10-11)

The independent machine-readable
[Ubuntu 24.04 PPA record](2026-10-11-ubuntu-24-04-ppa-native-canary.json)
is tied to protected `main@2fdde9b98f45960237c633a1eeae60134609a6db`.
It qualifies an **actually published and installed Ubuntu Noble amd64
10.0.7 binary**, not just a source upload, PPA index listing, or standalone
AppImage. It is independent of the earlier Windows and AppImage results.

A disposable **Ubuntu 24.04.5 amd64 container** used the official
`ppa:kicad/kicad-10.0-releases` repository with authenticated APT
metadata. Both `kicad` and `kicad-symbols` were installed at
`10.0.7~ubuntu24.04.1`; the native CLI reported exact version `10.0.7`,
and the standard Device symbol library was present. The published PPA
`Packages.gz` checksum for the `kicad` binary is recorded in the JSON
together with the symbols-package checksum, image digest, project revision,
locked uv/Python versions, and raw report SHA-256 digests.

| Native acceptance | Observed |
| --- | --- |
| Expected step statuses | **32/32** |
| Optional skips | **1** — Allegro import capability not advertised |
| Matched native/custom semantic comparisons | **5/5** |
| False PASS, false FAIL, divergence, invalid authority | **0 / 0 / 0 / 0** |
| Expected-negative ERC and DRC | Both native exit **5**, correctly treated as findings |
| Read-only output rejection | Native exit **4** under non-root execution |
| Failing fixtures | **0** |
| Repository input mutation | Prevented by read-only source mount; fixture copies isolated |

The native suite ran as a **non-root** user: a root process would bypass
ordinary read-only directory permissions, invalidating the negative-output
test. All report paths written by the raw canary remain local; the committed
evidence intentionally records bounded semantic projections and relative
output names, not absolute paths or free-form process logs.

This is native **CLI and fixture-contract** acceptance on one stable Ubuntu
distribution, not Linux editor GUI/IPC, macOS, successful autonomously
engineered real-board manufacturing, or a release/promotion recommendation.
At the same time, upstream Ubuntu **22.04 Jammy** 10.0.7 PPA binaries still
failed to build against the distribution's libgit2 1.1 headers; see
[issue #1181](https://github.com/oaslananka/kicad-mcp-pro/issues/1181).
Keep `compatibility.yaml`'s `latestVerified: 10.0.6` and its existing CI
version pins unchanged until the *whole* issue acceptance contract passes.

## Ubuntu 24.04 — real GUI / IPC under Xvfb (2026-10-11)

A distinct, genuine KiCad **10.0.7 PCB Editor GUI** test ran with
authenticated Ubuntu 24.04 Noble stable PPA binaries in a disposable Linux
container under the **Xvfb software display**, with a non-root GUI user,
read-only source checkout, isolated first-run preferences, and three versioned
library tables. The source was protected `main@fd58bf1319ffe3c7493a59be1b90538d1f3e2744`.

The [bounded Linux GUI qualification record](2026-10-11-linux-noble-ppa-gui-ipc.json)
confirms both real GUI test cases **PASS, 0 skips/failures**: closed editor
file-backed fallback, then four MCP PCB reads classified **live-gui** from
the running PCB Editor, followed by a different loaded PCB with altered
net names and the same four **live-gui** reads. This is **not** a stubbed IPC
connection or a headless kicad-cli-only test.

Private per-tool text, process logs, screenshots, paths and fixture workspaces
were **not** published. The repository stores only the constrained summary,
the observed backend classes, source provenance and SHA-256 hashes of private
raw evidence. The disposable container and its runtime files are removed
after evidence verification.

Xvfb is a software-driven display. This qualification does **not** assert
native Wayland desktop compatibility, real graphics-driver behaviour, macOS
GUI success, production release support, successful reference-board
manufacturing or the whole #1181 issue acceptance.

## macOS — signed KiCad 10.0.7 native CLI and real GUI/IPC (2026-10-11)

The independent
[hosted macOS native and GUI/IPC result](2026-10-11-macos-10-0-7-signed-native-gui-ipc.json)
records a **successful actual macos-15 execution**, not merely the existence
of a workflow. The bounded JSON was derived from the original GitHub
Actions [run #38093783089](https://github.com/oaslananka/kicad-mcp-pro/actions/runs/38093783089)
on exact source `d0ce717cee95630f0a7d8f65a3f725005a82a48f`.
The original artifact identifier and SHA-256 of its downloaded
`summary.json` are retained for independent provenance.

| Actual macOS 10.0.7 gate | Verified observation |
| --- | --- |
| Official KiCad universal DMG | Exact SHA-256 captured; Apple app code signature valid |
| Version and MCP library binding | Native CLI 10.0.7, symbols bound to the **same signed app bundle** |
| Native expected-step statuses | **32/32**, native failures 0 |
| Native-vs-MCP differential comparisons | **5/5 matches** |
| False pass / false fail / divergence / unavailable authority | **0 / 0 / 0 / 0** |
| Real PCB Editor GUI/IPC | **2/2 passing**, 0 skips/failures, including second-board switch |
| Overall strict result | **PASS** |

The first macOS native run failed because of an incorrect packaged library
table source and premature shell exit. Two subsequent runs genuinely
passed GUI/IPC but only matched **4/5** native/MCP semantic comparisons:
the gallery ESP32-C3 WROOM-02 breakout's pin-membership connectivity
groups disagreed. Root cause was that MCP's KiCad CLI library discovery
ignored the mounted app bundle's
`KiCad.app/Contents/SharedSupport/symbols`, producing missing or
unrelated pin geometry while native KiCad read the correct libraries.
The fix in protected [PR #1204](https://github.com/oaslananka/kicad-mcp-pro/pull/1204)
restores 5/5 without loosening any native or GUI criteria. Protected
[PR #1205](https://github.com/oaslananka/kicad-mcp-pro/pull/1205)
keeps that behavior and also resolves the subsequent SonarCloud
`python:S3776` maintainability finding, with zero new Sonar issues
on its passing PR.

The manually dispatched
[`kicad-10-0-7-macos-gui-ipc-qualification.yml`](https://github.com/oaslananka/kicad-mcp-pro/blob/main/.github/workflows/kicad-10-0-7-macos-gui-ipc-qualification.yml)
downloads the **official universal 10.0.7 DMG** from the CERN or MIT KiCad
stable mirror, verifies its embedded KiCad.app **Apple code signature**,
runs the extracted exact-version native CLI with the locked Python toolchain,
and then requires the **real PCB Editor GUI IPC** smoke: closed-GUI
fallback, four live-gui MCP readers, and a second loaded PCB.
It operates only on a disposable `macos-15` GitHub runner with isolated
first-run preferences, `contents: read` token permissions and no
schedule/PR triggers. The only uploaded evidence is a bounded result
without private GUI logs, screenshots, paths, or installation text.

The verified success belongs to the **exact feature revision** above;
merging its fix and the behavior-preserving follow-up into protected main
does not turn a historical runner result into a fresh run of every native
test on every final main commit. The workflow remains opt-in, so platform
requalification is explicit. Hardware-dependent WindowServer,
non-hosted macOS configurations, and full autonomous manufacture remain
out of scope.

## Ubuntu 22.04 — upstream 10.0.7 source/build incompatibility

On 2026-10-11, the official KiCad 10 stable Jammy PPA still publishes
10.0.6 as the latest amd64 `kicad` binary. Its 10.0.7
[amd64 build](https://launchpad.net/~kicad/+archive/ubuntu/kicad-10.0-releases/+build/33830758)
and [arm64 build](https://launchpad.net/~kicad/+archive/ubuntu/kicad-10.0-releases/+build/33830759)
both report **Failed to build**. Native compile logs identify
`common/local_history.cpp:1624` using `git_packbuilder_name`, which
is unavailable in Jammy's `libgit2-dev` 1.1 API. KiCad's upstream
10.0.6-to-10.0.7 change added this packbuilder-name dependency.

This is an **upstream binary package build gate**, not a failure of
KiCad MCP Pro's Python DRC/parser or GUI logic. Remediation belongs
to KiCad upstream packagers (e.g. correctly version-gating the API
without weakening pack/rewrite semantics, or using a tested compatible
libgit2 package). Do not install an unreviewed libgit2 override or
claim Jammy compatibility using a different distro's binary.


## Decision matrix — scope of #1181 at 2026-10-11

Each row is a separately source-bound check, **not** proof that all rows ran
on the same image or source commit. Native canary success means correct
pass/fail classification and matching semantic authority, not that
deliberately defective ERC/DRC designs were clean.

| Contract | Source-backed observation | Qualification boundary |
| --- | --- | --- |
| Native CLI 10.0.7, expected/negative status and five differential operations | Linux AppImage, Windows installer and Ubuntu Noble PPA: **32/32 expected statuses** and **5/5 semantic matches** | Only their recorded run revisions; optional documented capability skips remain |
| Actual editor GUI/IPC, fallback and second-board switch | Windows interactive runner **2/2**; Ubuntu Noble PPA Xvfb **2/2**; signed macOS DMG **2/2** | Xvfb is not physical Wayland/GPU; each result is OS- and revision-bound |
| Native DRC/ERC semantic consumer | Structured violation type/bucket/severity differential passed; deliberate DRC and ERC negative fixtures fail closed | Human-readable short-net description differs between 10.0.6 and 10.0.7 |
| Gallery-board *regression* | Public ESP32-C3 WROOM-02 breakout native/MCP connectivity member-set hash now matches on actual macOS 10.0.7; this was the initial 4/5 Mac blocker | A preexisting gallery board is **not** an autonomous from-spec reference-board success |
| Real agent-authored reference-board manufacturing | **Not qualified**; [#729](https://github.com/oaslananka/kicad-mcp-pro/issues/729) and [#730](https://github.com/oaslananka/kicad-mcp-pro/issues/730) require complete attempt accounting, independently verified ERC/DRC and reproducible fabrication outputs | Do not claim any STM32/ESP32-C6/RP2350 project is accepted until individual benchmark evidence exists |
| Ubuntu 22.04 Jammy 10.0.7 | Official stable PPA amd64/arm64 failed to build against legacy distro libgit2; legacy 10.0.6 workflow stays intact | Ubuntu 22.04 is upstream unsupported; no invented 10.0.7 Jammy build or cross-distro workaround |
| Global compatibility / release pin | **Retain `latestVerified: 10.0.6`**, no 10.0.7 promotion, release/tag or manufacturing claim | Requires explicit broader issue review and genuinely successful outstanding acceptance gates |

**Decision:** the evidence supports *specific native KiCad 10.0.7 CLI and
real GUI/IPC contracts* on those measured environments, while the full
#1181 promotion gate remains **open**. The old real macOS 4/5 divergence
was fixed and proved **5/5**; the incomplete autonomous real-board corpus
is a separate product-quality boundary. Retaining the current global pin
avoids conflating bounded platform acceptance with broader software
support, manufacturing readiness, or approval to publish a release.

# KiCad 10.0.7 — current-main platform and fixture checkpoint

**11 October 2026**, issue [#1181](https://github.com/oaslananka/kicad-mcp-pro/issues/1181).
All fresh measurements in the adjacent [bounded machine-readable checkpoint](2026-10-11-main-qualification.json) relate to the same **source revision**
`ee60c037a25187b6d2487b45d085781c6986f25b`; older Mac evidence is separately identified. This is a **compatibility evaluation**, not a benchmark success, manufacturing sign-off or new release claim.

## Evidence on this exact commit

| Platform / scope | Test verdict | Primary evidence |
| --- | --- | --- |
| Physical Ubuntu x64 KiCad 10.0.7 native CLI | **32/32 expected canary steps**, five of five native/custom semantic matches, zero unexpected differences | Local isolated full canary; original checkout clean afterward; expected dirty ERC and DRC return **5**, not a clean-board PASS |
| Hosted Windows 2025, official isolated KiCad 10.0.7 installer | Authenticode **Valid**, signed by KiCad Services Corporation; **32/32 expected native steps**, **5/5 semantics**, zero false passes/fails or divergence | [Run #38170396646](https://github.com/oaslananka/kicad-mcp-pro/actions/runs/38170396646), artifact `kicad-10-0-7-windows-native` with signed-installer SHA-256 `ce3881b6a9188eb34ac1ebaaec7651149e8a025206410addfb11a1a9656ecf95` |
| Hosted Windows 2025, actual PCB Editor | **2/2 GUI/IPC tests**, zero skipped, zero failures; confirms live project switching, not fabrication readiness | [Run #38170399571](https://github.com/oaslananka/kicad-mcp-pro/actions/runs/38170399571), artifact `kicad-10-0-7-windows-gui-ipc` |
| Hosted macOS 15, signed official 10.0.7 DMG | **32/32 native canary**, **5/5 semantic matches**; **2/2 live PCB Editor GUI/IPC** tests, zero failures/skips, valid signed installer | [Run #38170872908](https://github.com/oaslananka/kicad-mcp-pro/actions/runs/38170872908), artifact `kicad-10-0-7-macos-native-gui-ipc` |
| Hosted macOS 15, signed official 10.0.7 DMG | **32/32 native canary**, **5/5 semantic matches**; **2/2 live PCB Editor GUI/IPC** tests, zero failures/skips, valid signed installer | [Run #38170872908](https://github.com/oaslananka/kicad-mcp-pro/actions/runs/38170872908), artifact `kicad-10-0-7-macos-native-gui-ipc` |
| Physical Windows x64 KiCad 10.0.7 maintained fixture set | **6 fixture trees, 19 bounded native CLI operations**, source SHA-256 snapshots of **21 input files unchanged**; Gerber/drill/netlist output produced where applicable | Disposable copied fixtures; native DRC/ERC negative outcomes retained, not reclassified as clean or successful manufacturing |

The six Windows fixtures were `clean-led-kicad10`, `large-board`,
`multi-sheet-schematic`, `kicad-10-0-3-regressions`,
`drc-courtyard-error`, and `erc-power-pin-error`. The maintained
`clean-led-kicad10` **source** itself has **17 DRC violations and four
unconnected items** under KiCad 10.0.7 on **both Linux and Windows**. Native
CLI return code **5** is correct for a non-clean board. Do not confuse this
input with the canary's separately constructed clean fixture, which returns
zero in its own context. The evidence verifies **tool diagnostics and export
contracts**, not the electrical validity of these PCB designs. Source files
were not modified; all products and test configuration were written under
isolated temporary roots, not into user KiCad projects.

The Windows official native canary permits **two explicit skips**: CLI Allegro
import is not advertised, and Linux filesystem-specific read-only permission
checks cannot be modeled on Windows. The canary checks each expected native
result, including deliberate negative ERC/DRC return codes. `32/32` refers
to expected-step semantics, **not 32 clean PCB designs**.

## Compatibility gate — do not promote yet

KiCad upstream [released 10.0.7](https://www.kicad.org/blog/2026/10/KiCad-10.0.7-Release/).
The [maintained Chocolatey KiCad package](https://community.chocolatey.org/packages/kicad)
was still listed at **10.0.6** at this checkpoint. The project's primary
Windows canary matrix currently obtains its pinned version via Chocolatey.
An unconditional `compatibility.yaml` `latestVerified: 10.0.7` would therefore
implicitly request an unconfirmed Chocolatey package in that existing CI lane.
The isolated Windows 10.0.7 validation explicitly installs the signed official
upstream binary instead; it does **not** demonstrate the Chocolatey package's
availability.

Ubuntu 22.04's upstream stable PPA 10.0.7 build separately fails with legacy
libgit2; retain its supported **10.0.6 legacy lane**, without grafting an
unreviewed libgit2 or borrowing a different Ubuntu release's package.
The `kicad10FeatureParity.baseline` remains tied to a reviewed **10.0.6**
parity document. Promotion requires a distinct, reviewed 10.0.7 baseline and
an appropriate Windows package/official-installer CI strategy. Preserve the
last globally qualified `10.0.6` pin, documentation and required workflow
until those release-support gates are proven.

**Outstanding:** qualify the available Windows distribution path as part of
the *required* primary CI (or wait for a verified Chocolatey 10.0.7 package),
retain the separate legacy Ubuntu 22.04 exception, and migrate the audited
feature-parity documentation/tests atomically with the new version pin.
Finally, [#729](https://github.com/oaslananka/kicad-mcp-pro/issues/729)
and [#730](https://github.com/oaslananka/kicad-mcp-pro/issues/730)
remain independent *real agent-authored manufacturing* acceptance gates. Do not
promote or close #1181 on the strength of successful fixture exports alone.

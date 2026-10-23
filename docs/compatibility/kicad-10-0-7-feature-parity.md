# KiCad 10.0.7 Feature Parity

This page is the human-readable view of
[`compatibility.yaml`](https://github.com/oaslananka/kicad-mcp-pro/blob/main/compatibility.yaml) `kicad10FeatureParity`. It
tracks KiCad 10.0.7 parity separately from the current KiCad 11 readiness plan
so release gates stay focused on the stable KiCad line.

**Scope and decision (2026-10-23):** Version 10.0.7 is the latest verified
patch for the **already supported product surfaces**. All core native CLI and
real GUI/IPC host contracts were validated against exact source
`3978af8710ca1b117f0a037f103d873ef5ab6564` on Ubuntu 24.04, Windows 2025,
and macOS 15. See the [cross-platform artifact audit](../evidence/kicad-10-0-7/2026-10-23-platform-checkpoint.md),
and [patch-specific regression review](../evidence/kicad-10-0-7/2026-10-12-feature-parity-audit.md).

**Qualified boundaries:** 32 native canary steps and five semantic differential
cases on Windows/macOS, actual PCB Editor IPC smoke (two passing tests per host),
real macOS Schematic Editor BOM-Cancel/undo, numeric ERC JSON units, flat
multi-root schematic PDF, and Gerber drill-mark outputs. The official 10.0.7
installer passed signature/hash verification. Chocolatey 10.0.7 was approved
on 2026-10-16; its package metadata references the **same verified official
installer SHA-256**. An independent physical Windows 11 Chocolatey metadata
query returned version 10.0.7. These claims do not certify electrical designs.

**Explicitly unqualified optional upstream additions:**
- `kicad-python 0.9.0`-only IPC tables, reference points and embedded-file
  wrappers: **blocked**, because the latest published stable binding is 0.8.0
  and this repo locks tested 0.7.1. The existing IPC support is *not* a claim
  to implement the new KiCad 10.0.7 wrapper contracts; see
  `scripts/kicad_107_ipc_binding_gate.py` (fail closed).
- KiCad PCB Editor's new Allegro 24.x/25.x graphical importer does **not** imply
  `kicad-cli pcb import --format allegro`; actual 10.0.7 CLI help does not
  expose that format. The product CLI importer remains **blocked**.
- Ubuntu 22.04 retains the independently verified **10.0.6** legacy lane due
  to the observed upstream libgit2 failure; qualifying Ubuntu 24.04 10.0.7
  does not waive legacy requirements.
- Real manufacturing, connector mating, power return, decoupling and fully
  autonomous reference-board acceptance are **not** approved by this baseline.
  Follow #1381, #1393, #1214, #729 and #730 separately. Release PR #1250
  remains independently approval-gated.

The original [10.0.6 historical baseline](kicad-10-0-6-feature-parity.md)
remains available; do not rewrite its feature histories.

Status vocabulary:

| State            | Meaning                                                                                   |
| ---------------- | ----------------------------------------------------------------------------------------- |
| `supported`      | Product support exists and is backed by a test, fixture, command probe, or smoke path.    |
| `not-applicable` | KiCad-native GUI behavior is intentionally outside the extension or MCP product surface.  |
| `partial`        | Some product support exists, but a tracked gap remains.                                   |
| `blocked`        | Product support is intentionally prevented by an upstream or policy boundary.             |
| `future`         | The upstream feature exists or is expected, but product adoption is scheduled separately. |

## Importers

| Feature id    | State       | Product boundary                                                                                                | Evidence or issue                                                                             |
| ------------- | ----------- | --------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------- |
| `altium`      | `supported` | Extension import command and MCP manufacturing probe after `kicad-cli pcb import --help` advertises the format. | `tests/integration/test_export_tools.py`, `tests/integration/test_manufacturing_tools.py`     |
| `allegro`     | `blocked`   | Extension command is registered for future compatibility but hidden unless CLI support appears.                 | [#39](https://github.com/oaslananka/kicad-mcp-pro/issues/39), `kicad-10-0-3-regressions`        |
| `cadstar`     | `supported` | Extension command is probe-gated by CLI help.                                                                   | `tests/integration/test_export_tools.py`                                                      |
| `eagle`       | `supported` | Extension command is probe-gated by CLI help.                                                                   | `tests/integration/test_export_tools.py`                                                      |
| `fabmaster`   | `supported` | Extension command is probe-gated by CLI help.                                                                   | `tests/integration/test_export_tools.py`                                                      |
| `geda_lepton` | `supported` | Extension and MCP support require the installed CLI to advertise `geda`.                                        | `tests/integration/test_manufacturing_tools.py`                                               |
| `pads`        | `supported` | Extension, MCP, fixture, and canary coverage exercise the PADS import boundary.                                 | `tests/unit/test_kicad_canary.py`                                                             |
| `pcad`        | `supported` | Extension command is probe-gated by CLI help.                                                                   | `tests/integration/test_export_tools.py`                                                      |
| `solidworks`  | `supported` | Extension command is probe-gated by CLI help.                                                                   | `tests/integration/test_export_tools.py`                                                      |

## Exports

| Feature id                           | State       | Product boundary                                                                                     | Evidence or issue                                                |
| ------------------------------------ | ----------- | ---------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------- |
| `gerber`                             | `supported` | MCP manufacturing and extension export workflows depend on the KiCad CLI Gerber export.              | `scripts/kicad_canary.py`                                        |
| `drill`                              | `supported` | MCP manufacturing and extension export workflows depend on the KiCad CLI drill export.               | `scripts/kicad_canary.py`                                        |
| `pdf`                                | `supported` | Schematic and PCB PDF exports are part of the primary KiCad canary plan.                             | `tests/unit/test_kicad_canary.py`                                |
| `pcb_pdf_property_popup_suppression` | `supported` | KiCad 10.x PDF property popup suppression is covered by a fixture and canary probe.                  | `kicad-10-0-3-regressions`                                       |
| `ipc2581`                            | `supported` | Extension command and MCP `export_ipc2581` tool both expose the export.                              | `tests/integration/test_pcb_export_validation_surface.py`        |
| `odbpp`                              | `supported` | Extension command and MCP `export_odb` tool expose ODB++ behind capability checks.                   | `tests/integration/test_export_tools.py`                         |
| `step`                               | `supported` | MCP `export_step` and `export_3d_step` tools cover the KiCad CLI STEP export.                        | `tests/integration/test_export_tools.py`                         |
| `stepz`                              | `supported` | MCP `export_stepz` exposes KiCad's `stpz` CLI export for headless STEPZ/GZIP-compressed STEP output. | `tests/integration/test_export_tools.py`                         |
| `xao`                                | `supported` | MCP `export_xao` exposes the KiCad CLI XAO export for headless interchange workflows.                | `tests/integration/test_export_tools.py`                         |

## GUI Editor

| Feature id                  | State            | Product boundary                                                                                                       | Evidence or issue                                             |
| --------------------------- | ---------------- | ---------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------- |
| `design_blocks`             | `supported`      | Product support is headless through parser coverage and MCP `pcb_block_*` tools.                                       | `tests/integration/test_pcb_tools.py`                         |
| `graphical_drc_rule_editor` | `not-applicable` | The native GUI editor remains a KiCad-owned surface; product support is textual `.kicad_dru` guidance and diagnostics. | `docs/kicad10/graphical-drc.md`                               |
| `variants`                  | `supported`      | Extension variants view and MCP `variant_*` tools cover list, activation, diff, and export integration.                | `tests/integration/test_export_tools.py`                      |
| `barcode_support`           | `supported`      | MCP `pcb_add_barcode` supports headless barcode insertion; visual editing stays in KiCad.                              | `tests/unit/test_kicad10_parity_tools.py`                     |
| `time_domain_tuning`        | `supported`      | MCP tuning helpers model and validate routing intent; the native interactive routing UX remains KiCad-owned.           | `tests/integration/test_routing_tools.py`                     |

## IPC

| Feature id                      | State       | Product boundary                                                                       | Evidence or issue                                                 |
| -------------------------------- | ----------- | -------------------------------------------------------------------------------------- | ----------------------------------------------------------------- |
| `kicad_python_ipc`              | `supported` | KiCad IPC is the supported live-editor direction for current and future KiCad lines.   | `tests/gui/test_kicad_gui_live_context.py`                        |
| `ipc_107_expanded_objects`       | `blocked`   | New 10.0.7 tables, reference points and embedded-file wrappers need the unpublished stable `kicad-python >=0.9.0` and real GUI tests. | `scripts/kicad_107_ipc_binding_gate.py` |
| `swig_pcbnew_direct_dependency` | `blocked`   | Production direct `pcbnew` imports are forbidden because SWIG bindings are deprecated. | [#192](https://github.com/oaslananka/kicad-mcp-pro/issues/192)        |

## Product Surfaces

| Feature id                        | State       | Product boundary                                                                        | Evidence or issue                                                 |
| --------------------------------- | ----------- | ----------------------------------------------------------------------------------------- | ----------------------------------------------------------------- |
| `status_surface`                  | `supported` | The MCP server-info endpoint exposes detected KiCad line and feature gates.             | `tests/unit/test_server_info_contract.py`                         |
| `importer_command_gating`         | `supported` | Import commands are unavailable until the matching CLI capability probe passes.         | `tests/integration/test_export_tools.py`                          |
| `server_info_capability_contract` | `supported` | MCP server-info compatibility and capability payloads are schema and docs gated.        | `tests/unit/test_server_info_contract.py`                         |
| `empty_project_read_tools`        | `partial`   | File-backed empty-project behavior is tracked outside this matrix.                      | [#41](https://github.com/oaslananka/kicad-mcp-pro/issues/41)        |
| `ipc_state_consistency`           | `partial`   | IPC lifecycle consistency is tracked in the MCP compatibility milestone.                | [#42](https://github.com/oaslananka/kicad-mcp-pro/issues/42)        |

## Release

| Feature id               | State       | Product boundary                                                                        | Evidence or issue                         |
| ------------------------ | ----------- | ----------------------------------------------------------------------------------------- | ----------------------------------------- |
| `vsix_provenance`        | `supported` | VSIX release evidence includes checksums, SBOM, and artifact attestations.              | `.github/workflows/publish-python.yml`    |
| `wheel_provenance`       | `supported` | Python release evidence includes checksums, SBOM, trusted publishing, and attestations. | `.github/workflows/publish-python.yml`    |
| `npm_tarball_provenance` | `supported` | npm launcher release evidence includes checksums, SBOM, and provenance.                 | `.github/workflows/publish-npm.yml`       |

## KiCad 11 Readiness

KiCad 11 readiness is represented separately from KiCad 10.0.7 parity:

| Feature id           | State       | Product boundary                                                                                   | Evidence or issue                                                 |
| -------------------- | ----------- | -------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------- |
| `protocol_upgrade`   | `future`    | MCP protocol and KiCad 11 support planning remain separate from the stable KiCad 10 gate.          | [#411](https://github.com/oaslananka/kicad-mcp-pro/issues/411)        |
| `nightly_canary`     | `supported` | Manual nightly canary commands track prerelease behavior without changing the stable support line. | `corepack pnpm run test:kicad-cli-contract:nightly`               |
| `swig_removal_guard` | `supported` | The direct-`pcbnew` guard keeps production code away from APIs planned for removal.                | `scripts/check_no_pcbnew.py`                                      |

## Validation

Linux and macOS:

```bash
corepack pnpm run compat:check
corepack pnpm run test:contract
corepack pnpm run test:fixtures
```

Windows 11 PowerShell:

```powershell
corepack pnpm run compat:check
corepack pnpm run test:contract
corepack pnpm run test:fixtures
```

The compatibility gate verifies that every supported item has product evidence,
every partial or blocked item links a GitHub issue, and every feature id in the
matrix appears on this page.

## Source Verification

Checked on 2026-10-23 against the qualified KiCad 10.0.7 native and
actual-editor workflows:

- [KiCad 10.0.7 release notes](https://www.kicad.org/blog/2026/10/KiCad-10.0.7-Release/)
- [KiCad 10.0.7 GitHub release tag](https://github.com/KiCad/kicad-source-mirror/releases/tag/10.0.7)
- [KiCad 10.0 CLI reference](https://docs.kicad.org/10.0/en/cli/cli.html)
- [KiCad 10.0 PCB Editor reference](https://docs.kicad.org/10.0/en/pcbnew/pcbnew.html)
- [KiCad PCB Python bindings deprecation notice](https://dev-docs.kicad.org/en/apis-and-binding/pcbnew/)
- [Stable official Python binding package](https://pypi.org/project/kicad-python/)
- [Exact-source Windows/macOS/Ubuntu GUI and CLI artifact matrix](../evidence/kicad-10-0-7/2026-10-23-platform-checkpoint.md)

The installed **10.0.7** CLI was queried directly using
`kicad-cli pcb import --help`; its advertised format hints include `auto`,
`pads`, `altium`, `eagle`, `cadstar`, `fabmaster`, `pcad` and `solidworks`,
but **not** `allegro`. Allegro 24.x/25.x import improvements in the
upstream PCB Editor do not constitute a product CLI import capability.
The product's CLI Allegro feature therefore remains **blocked**. The
existing GUI-side Allegro fixes in **10.0.6** are recorded only in the
[historical 10.0.6 parity snapshot](kicad-10-0-6-feature-parity.md).

The `kicad-10-0-3-regressions` fixture remains intentionally named for the
patch release that introduced those snapshots. It is carried forward as a
historical regression corpus under the current 10.0.7 supported-surface
baseline without renaming its original snapshots. The legacy Ubuntu 22.04
canary separately tests its preserved 10.0.6 binary.

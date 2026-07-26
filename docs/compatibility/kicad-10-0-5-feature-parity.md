# KiCad 10.0.5 Feature Parity

This page is the human-readable view of
[`compatibility.yaml`](https://github.com/oaslananka/kicad-mcp-pro/blob/main/compatibility.yaml) `kicad10FeatureParity`. It
tracks KiCad 10.0.5 parity separately from the current KiCad 11 readiness plan
so release gates stay focused on the stable KiCad line.

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
| `allegro`     | `blocked`   | Extension command is registered for future compatibility but hidden unless CLI support appears.                 | [#191](https://github.com/oaslananka/kicad-mcp-pro/issues/191), `kicad-10-0-3-regressions`        |
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
| ------------------------------- | ----------- | -------------------------------------------------------------------------------------- | ----------------------------------------------------------------- |
| `kicad_python_ipc`              | `supported` | KiCad IPC is the supported live-editor direction for current and future KiCad lines.   | `tests/gui/test_kicad_gui_live_context.py`                        |
| `swig_pcbnew_direct_dependency` | `blocked`   | Production direct `pcbnew` imports are forbidden because SWIG bindings are deprecated. | [#192](https://github.com/oaslananka/kicad-mcp-pro/issues/192)        |

## Product Surfaces

| Feature id                        | State       | Product boundary                                                                        | Evidence or issue                                                 |
| --------------------------------- | ----------- | --------------------------------------------------------------------------------------- | ----------------------------------------------------------------- |
| `status_surface`                  | `supported` | The MCP server-info endpoint exposes detected KiCad line and feature gates.             | `tests/unit/test_server_info_contract.py`                         |
| `importer_command_gating`         | `supported` | Import commands are unavailable until the matching CLI capability probe passes.         | `tests/integration/test_export_tools.py`                          |
| `server_info_capability_contract` | `supported` | MCP server-info compatibility and capability payloads are schema and docs gated.        | `tests/unit/test_server_info_contract.py`                         |
| `empty_project_read_tools`        | `partial`   | File-backed empty-project behavior is tracked outside this matrix.                      | [#210](https://github.com/oaslananka/kicad-mcp-pro/issues/210)        |
| `ipc_state_consistency`           | `partial`   | IPC lifecycle consistency is tracked in the MCP compatibility milestone.                | [#192](https://github.com/oaslananka/kicad-mcp-pro/issues/192)        |

## Release

| Feature id               | State       | Product boundary                                                                        | Evidence or issue                         |
| ------------------------ | ----------- | --------------------------------------------------------------------------------------- | ----------------------------------------- |
| `vsix_provenance`        | `supported` | VSIX release evidence includes checksums, SBOM, and artifact attestations.              | `.github/workflows/publish-python.yml`    |
| `wheel_provenance`       | `supported` | Python release evidence includes checksums, SBOM, trusted publishing, and attestations. | `.github/workflows/publish-python.yml`    |
| `npm_tarball_provenance` | `supported` | npm launcher release evidence includes checksums, SBOM, and provenance.                 | `.github/workflows/publish-npm.yml`       |

## KiCad 11 Readiness

KiCad 11 readiness is represented separately from KiCad 10.0.5 parity:

| Feature id           | State       | Product boundary                                                                                   | Evidence or issue                                                 |
| -------------------- | ----------- | -------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------- |
| `protocol_upgrade`   | `future`    | MCP protocol and KiCad 11 support planning remain separate from the stable KiCad 10 gate.          | [#209](https://github.com/oaslananka/kicad-mcp-pro/issues/209)        |
| `nightly_canary`     | `supported` | Manual nightly canary commands track prerelease behavior without changing the stable support line. | `corepack pnpm run test:kicad-cli-contract:nightly`               |
| `swig_removal_guard` | `supported` | The direct-`pcbnew` guard keeps production code away from APIs planned for removal.                | `scripts/check_no_pcbnew.py`                                      |

## Validation

Linux and macOS:

```bash
corepack pnpm run check:compatibility
corepack pnpm run test:contract
corepack pnpm run test:fixtures
```

Windows 11 PowerShell:

```powershell
corepack pnpm run check:compatibility
corepack pnpm run test:contract
corepack pnpm run test:fixtures
```

The compatibility gate verifies that every supported item has product evidence,
every partial or blocked item links a GitHub issue, and every feature id in the
matrix appears on this page.

## Source Verification

Checked on 2026-07-26:

- [KiCad 10.0.5 release notes](https://www.kicad.org/blog/2026/07/KiCad-10.0.5-Release/)
- [KiCad 10.0.5 GitHub release tag](https://github.com/KiCad/kicad-source-mirror/releases/tag/10.0.5)
- [KiCad 10.0 CLI reference](https://docs.kicad.org/10.0/en/cli/cli.html)
- [KiCad 10.0 PCB Editor reference](https://docs.kicad.org/10.0/en/pcbnew/pcbnew.html)
- [KiCad PCB Python bindings deprecation notice](https://dev-docs.kicad.org/en/apis-and-binding/pcbnew/)
- [KiCad nightly and release candidate guidance](https://www.kicad.org/help/nightlies-and-rcs/)

KiCad 10.0.5 changed `pcb render --use-board-stackup-colors` into a plain opt-in flag. The MCP command emits it only when explicitly requested; `test_render_stackup_colors_flag_is_opt_in` protects that contract.

The `kicad-10-0-3-regressions` fixture remains intentionally named for the
patch release that introduced those snapshots. It is carried forward as a
regression corpus under the 10.0.5 primary baseline rather than renamed, so
historic fixture provenance stays stable while the canary lane verifies the
installed 10.0.5 CLI.

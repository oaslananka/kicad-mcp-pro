# KiCad 10.0.7 — exact-main qualification checkpoint

**2026-10-23 · [Issue #1181](https://github.com/oaslananka/kicad-mcp-pro/issues/1181) · reviewed source `3978af8710ca1b117f0a037f103d873ef5ab6564`.**

This checkpoint distinguishes genuine native command-line, live GUI/IPC, and real-fixture evidence. It does **not** qualify manufacturing, autonomous PCB design, all 10.0.7 patch APIs, or a public software release. Hosted workflow success describes the workflow's explicitly tested contracts, not every possible KiCad operation.

## Exact source evidence

| Platform and test | Recorded evidence | Qualification boundary |
| --- | --- | --- |
| Ubuntu 24.04, genuine 10.0.7 primary canary | [KiCad Live E2E #39900817676](https://github.com/oaslananka/kicad-mcp-pro/actions/runs/39900817676), **success** on exact source, including current-stable native canary | The separately retained Ubuntu 22.04 legacy KiCad **10.0.6** canary also passed in the same run; Jammy 10.0.7 is **not** claimed |
| Windows 2025, official signed isolated 10.0.7 | [Windows qualification #39900817488](https://github.com/oaslananka/kicad-mcp-pro/actions/runs/39900817488), **success**; downloaded artifact independently inspected: **32/32** expected canary steps, **5/5** semantics, zero false-pass/false-fail/divergence/infrastructure-invalid, and three targeted ERC/PDF/Gerber regressions **PASS** | Native CLI and explicitly covered contracts; not a GUI test |
| Actual Windows 11 installation, 10.0.7 | Independent isolated `clean-led-kicad10` read-only fixture check: schematic ERC reports **3** expected violations (exit **5**), PCB DRC reports **17** violations and **4** unconnected (exit **5**); inputs retain published SHA-256 | Correct fail-closed diagnostics on a deliberately non-clean test board; not an electrical or manufacturing PASS |
| Windows 2025 actual editor GUI/IPC | [Same-source qualification #39960284615](https://github.com/oaslananka/kicad-mcp-pro/actions/runs/39960284615), **success**; independently downloaded bounded artifact: **2/2 actual GUI/IPC tests**, 0 failures/skips, real live project switch and four MCP read tools, report `verdict=pass` | Exact source `3978af87`; real hosted interactive PCB Editor, not a manufacturing test |
| macOS 15, signed 10.0.7, real GUI/IPC | [Same-source qualification #39960288521](https://github.com/oaslananka/kicad-mcp-pro/actions/runs/39960288521), **success**; downloaded bounded artifacts verify signed DMG, **32 native steps**, **5/5 semantic matches**, **2/2 real GUI/IPC tests**, 0 failed/skipped, and **Schematic Editor BOM Cancel acceptance PASS**, including project integrity | Exact source `3978af87`; genuine hosted editor session, not unrestricted IPC-object parity or fabrication |
| Real reference-board MCP quality review, 10.0.7 on original source | [#1380 closure evidence](https://github.com/oaslananka/kicad-mcp-pro/issues/1380#issuecomment-6357467572) on merged `main@3978af87`: saved-PCB footprint parity **45/45 PASS**, PCB transfer **169/169 PASS**, DRC **PASS**, overall **WARN**, unchanged board digest | Read-only correctness and preservation of warnings, **not** physical manufacturing approval |

The deliberately faulty `clean-led-kicad10` fixture is identified by PCB SHA-256 `7460ea575de1083ebebec0efba2c8560c186e5a81c3cd2e37c775eea03927aa2` and schematic SHA-256 `99687419c11831ccae6776c5e7face48697e7587e7ea09ee210a675afb6b7b69`. Neither source file changed during the independent Windows native check. The Windows-hosted native canary's signed official installer digest in its artifact is `ce3881b6a9188eb34ac1ebaaec7651149e8a025206410addfb11a1a9656ecf95`.

## Historical pre-promotion hold (collected before subsequent review)

**Historical context:** The below decision was recorded before the separate
[10.0.7 reviewed supported-surface parity baseline](../../compatibility/kicad-10-0-7-feature-parity.md)
was proposed. It explains why the evidence-only PR #1431 did not itself change
compatibility pins. Consult the current compatibility matrix for the latest
supported-surface version; no subsequent change retroactively certifies
unpublished expanded IPC wrappers, Jammy 10.0.7 or manufacturing.

- `compatibility.yaml` still explicitly says `kicad.latestVerified: 10.0.6` and `kicad10FeatureParity.baseline: 10.0.6`, and the [reviewed 10.0.6 feature-parity baseline](../../compatibility/kicad-10-0-6-feature-parity.md) remains the project's normative baseline. The repository's compatibility checker requires these values to agree. Updating one number without the other and without a reviewed parity baseline would be inaccurate.
- The required current-stable Ubuntu 24.04 lane and separate Windows official-installer native qualification are proven. The separate Ubuntu 22.04/10.0.6 legacy lane must be preserved; Ubuntu 22.04 is not qualified for native KiCad 10.0.7. A Chocolatey default-package lane should not be silently assumed to provide 10.0.7.
- The [10.0.7 patch-specific feature audit](2026-10-12-feature-parity-audit.md) records bounded/unproven IPC object behavior and patch-specific feature contracts. Review and explicitly classify those before changing the product-wide feature-parity documentation and `latestVerified` baseline.
- Physical connector mating, power-return/decoupling and supplier annular-ring constraints remain separately blocked under [#1393](https://github.com/oaslananka/kicad-mcp-pro/issues/1393), [#1381](https://github.com/oaslananka/kicad-mcp-pro/issues/1381) and [#1214](https://github.com/oaslananka/kicad-mcp-pro/issues/1214). No generated Gerbers have been submitted for manufacture, and release PR [#1250](https://github.com/oaslananka/kicad-mcp-pro/pull/1250) is explicitly excluded.

**Next gate:** review the outstanding product-wide feature-parity and distribution-policy gaps, now that exact-source Windows/macOS GUI/IPC outcomes are verified; then propose the smallest reviewed release/support-policy migration separately, with explicit changes to the compatibility baseline and controlled CI lanes. Until that gate, keep issue #1181 open and the global version pin unchanged.

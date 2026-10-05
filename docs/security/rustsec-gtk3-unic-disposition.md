# RustSec GTK3 / rust-unic Advisory Disposition

This page records the reviewed RustSec dependency state tracked by [#779](https://github.com/oaslananka/kicad-mcp-pro/issues/779).

## Current state — 2026-10-05

Stable Tauri now provides a supported remediation for the rust-unic advisory family. From `main@0d73e7afcbb9e4cc98817ef44f7fc8fb8e8771de`, the repository's pinned Rust 1.97.1 toolchain resolves:

- `tauri 2.12.0`
- `tauri-build 2.7.1`
- `tauri-runtime 2.12.1`
- `tauri-runtime-wry 2.12.1`
- `tauri-utils 2.10.1`
- `wry 0.57.0`
- `urlpattern 0.6.0`

The generated lockfile removes all five `unic-* 0.9.0` packages without advisory suppression.

Pinned `cargo-audit 0.22.2` against that lockfile reports **0 vulnerabilities** and exactly **2 warning-kind findings**:

- `RUSTSEC-2024-0370` — `proc-macro-error 1.0.4`, unmaintained;
- `RUSTSEC-2024-0429` — `glib 0.18.5`, unsound.

Machine-readable resolver, MSRV, audit, hash, reachability, and platform evidence is in `docs/evidence/rustsec-gtk3-unic-audit-2026-10-05.json`.

## Remediated advisory family

The stable Tauri 2.12 / tauri-utils 2.10.1 / urlpattern 0.6.0 graph removes:

- `RUSTSEC-2025-0075`
- `RUSTSEC-2025-0080`
- `RUSTSEC-2025-0081`
- `RUSTSEC-2025-0098`
- `RUSTSEC-2025-0100`

These findings are removed from the reviewed baseline rather than ignored.

## Remaining upstream risk

The two remaining findings resolve through the Linux GTK3/WebKitGTK dependency chain. Explicit target-scoped `cargo tree` checks show `glib 0.18.5` and `proc-macro-error 1.0.4` on `x86_64-unknown-linux-gnu`, while both are absent for `aarch64-apple-darwin` and `x86_64-pc-windows-msvc`.

Application source searches under `src-tauri/src` find no direct `VariantStrIter` or rust-unic API use. The remaining two warnings are retained as reviewed, transitive upstream risk and must not be suppressed. Revisit them when stable Tauri/Wry removes the GTK3 0.18 chain or application reachability changes.

## MSRV and release-tool parity

`tauri 2.12.0`, `tauri-utils 2.10.1`, and `tauri-cli 2.12.0` each declare Rust 1.90 as their minimum supported Rust version. The repository toolchain remains Rust 1.97.1, while the desktop crate's declared `rust-version` is updated from 1.78 to 1.90.

The reviewed Tauri CLI pin remains synchronized between `scripts/dev-toolchain.env` and `.github/workflows/gui-release.yml`. Release jobs continue to install the exact reviewed CLI version with `--locked`.

## Required verification

This remediation does not weaken any gate. Required validation includes:

- locked Cargo metadata/check/test and GUI build/package lanes;
- Linux, macOS, and Windows desktop coverage as configured by repository workflows;
- pinned RustSec baseline validation;
- Dependency Review, CodeQL, Gitleaks, Semgrep, Sonar, and workflow policy;
- the aggregate Required PR Gate.

After merge, re-query OpenSSF Scorecard alert #53 against default-branch evidence. Do not dismiss or suppress the alert merely to improve its score. Keep #779 open while the two GTK/glib-chain findings remain unresolved.

## Historical evidence

The pre-remediation seven-warning inventory and original bounded disposition remain preserved in Git history and `docs/evidence/rustsec-gtk3-unic-audit-2026-09-09.json`.

# RustSec GTK3 / rust-unic Advisory Disposition

This page records the reproducible advisory inventory behind [#779](https://github.com/oaslananka/kicad-mcp-pro/issues/779) and OpenSSF Scorecard code-scanning alert #53 (`VulnerabilitiesID`, severity `error`), the reachability evidence for each advisory family, and the accepted-risk decision for the desktop (`src-tauri`) Cargo dependency tree.

## Reproduction

```bash
cd src-tauri
cargo audit --file Cargo.lock --json
```

- Tool: `cargo-audit-audit 0.22.2`
- Lockfile: `src-tauri/Cargo.lock`, SHA-256 `2cee389a2afc504b191750698542d8857a600d9d3f9127209393d3dfd21295a6`
- Repository commit: `449f27b0b40b03cebe7ef1cb84ab195dae5a4d9e`
- Result: `vulnerabilities.count = 0`, `warnings = 17` (16 `unmaintained`, 1 `unsound`)

cargo-audit's own severity model already separates these findings from exploitable vulnerabilities: none of the 17 findings are classified as an RustSec `Vulnerability`-kind advisory. All 17 are `warning`-kind (`unmaintained` or `unsound`), which is why `src-tauri/.cargo/audit.toml` already lists both kinds under `informational_warnings` — that setting predates this review and was not changed by it.

Full machine-readable evidence, including the reverse-dependency chain for each finding and the upstream tracking snapshot, is recorded in:

- `docs/evidence/rustsec-gtk3-unic-audit-2026-08-30.json`

## Advisory families

| Family | Advisories | Kind | Root package | Reachable from app code? |
| --- | --- | --- | --- | --- |
| GTK3 / gtk-rs bindings | `RUSTSEC-2024-0411`..`0420` (10 advisories) | unmaintained | `gtk 0.18.2` and its `-sys`/companion crates | No — transitive only |
| glib soundness | `RUSTSEC-2024-0429` | **unsound** | `glib 0.18.5` | No — transitive only |
| proc-macro-error | `RUSTSEC-2024-0370` | unmaintained | `proc-macro-error 1.0.4` | No — build-time transitive only |
| rust-unic | `RUSTSEC-2025-0075`, `0080`, `0081`, `0098`, `0100` | unmaintained | `unic-* 0.9.0` | No — transitive only |

## Reachability and exploitability evidence

`grep -RnE 'VariantStrIter|unic_char|unic::|unic_common|unic_ucd' src-tauri/src` returns no matches. Application code in `src-tauri/src` never calls `glib::VariantStrIter` (the unsound symbol behind `RUSTSEC-2024-0429`) or any `unic-*` API directly. Every one of the 17 findings enters the dependency graph transitively:

- **rust-unic family**: `unic-char-range <- unic-char-property <- unic-ucd-ident <- urlpattern <- tauri-utils <- tauri`/`tauri-build <- kicad-mcp-pro`. `urlpattern` is Tauri's own URL-pattern matcher; the repository never depends on `urlpattern` or `unic-*` directly.
- **GTK3 / glib family**: `gtk`/`glib`/`webkit2gtk`/`wry <- tauri` (also reachable via the tray/`libappindicator` path). `cargo tree -i glib` against the default target prints nothing; only `cargo tree -i glib --target all` resolves the chain, confirming these crates are pulled in exclusively under Tauri's `cfg(target_os = "linux")` GTK/WebKitGTK backend. They are absent from the macOS (WKWebView) and Windows (WebView2) dependency graphs.
- **proc-macro-error**: reached only as a build-time proc-macro dependency of `gtk3-macros`, itself only present on the Linux target.

No advisory in this set has a known proof-of-concept or CVE tied to reachable application behavior. The `unsound` classification on `glib 0.18.5` describes a soundness hazard in an API this codebase does not call.

## Upstream tracking

Upstream Tauri cannot remove the GTK3 chain today: Tauri's current development manifest still resolves Linux `gtk = 0.18` / `webkit2gtk = 2`, and this repository is already on the current stable `tauri 2.11.5`. The relevant upstream migration work, checked live on 2026-08-30:

| Tracking item | State | Notes |
| --- | --- | --- |
| [`tauri-apps/tauri#12561`](https://github.com/tauri-apps/tauri/issues/12561) — Upgrade `tauri-runtime-wry` to `gtk4-rs` | Open | Tracking issue for the runtime-side migration. |
| [`tauri-apps/tao#1104`](https://github.com/tauri-apps/tao/pull/1104) — Port to gtk4-rs | Open, not merged | Active as of 2026-08-18; ports `tao` (Tauri's windowing crate) from GTK3/webkit2gtk to GTK4/webkit6/soup3, which is the precondition for `wry`/`tauri` to drop the GTK3 chain. |

There is no compatible stable Tauri/wry release yet that removes any advisory in this set. A normal patch/minor dependency refresh cannot close this out; it is gated on the linked upstream PR/issue merging and a subsequent Tauri release adopting it.

## OpenSSF Scorecard alert #53

Read live via `gh api repos/oaslananka/kicad-mcp-pro/code-scanning/alerts/53` on 2026-08-30: `state: open`, `most_recent_instance.state: open`, `rule: VulnerabilitiesID`, `severity: error`, last updated `2026-08-10T12:10:21Z`. This is consistent with the cargo-audit reproduction above — the alert aggregates the same 17 RustSec advisories, none of which have a fix available yet, so the alert is expected to remain open until the upstream GTK4 migration lands and this repository upgrades to a Tauri/wry release that adopts it.

## Risk decision

- Do not suppress or dismiss Scorecard alert #53 to improve the score; it remains open and accurately reflects unresolved upstream advisories.
- Do not add per-advisory `cargo audit` ignores. The existing `informational_warnings = ["unmaintained", "unsound"]` setting in `src-tauri/.cargo/audit.toml` is a kind-level (not advisory-level) classification that predates this review; this document supplies the per-advisory reachability evidence the issue requires without narrowing CI enforcement further.
- Do not perform a GTK4 migration in this repository ahead of upstream Tauri/wry support landing; doing so would mean depending on unreleased/unpinned upstream crates.
- Accept the current risk as **low**: every advisory is transitive-only, unreachable from application code, and (for the GTK3/glib/proc-macro-error group) gated to a code path (Linux GTK backend) that the application does exercise on Linux, but not through the unsound/unmaintained symbols themselves.

## Revisit triggers

Re-run this review and update the evidence file when any of the following occurs:

1. `tauri-apps/tao#1104` merges, or `tauri-apps/tauri#12561` closes.
2. A new stable `tauri`/`wry` release changes the Linux GTK/glib dependency versions in `src-tauri/Cargo.lock`.
3. `cargo audit` reports a new advisory in this set as `vulnerability`-kind rather than `warning`-kind.
4. Scorecard alert #53 changes state (closed, reopened, or its aggregated advisory list changes).

## 2026-09-04 remediation recheck

The engineering-audit remediation re-ran `osv-scanner 2.4.0` from the repository root and reproduced the same 17 Rust advisories: 0 Critical, 0 High, 1 Medium (`RUSTSEC-2024-0429`, `glib 0.18.5`), and 16 Unknown/informational advisories. No advisory was removed by the current compatible dependency set.

A fresh `cargo tree -i glib@0.18.5` under `src-tauri` still resolves the Linux chain through `gtk 0.18.2`, `webkit2gtk 2.0.2`, `wry 0.55.1`, and `tauri 2.11.5`, including the tray/runtime paths. `cargo update -p tauri --dry-run` reports `Locking 0 packages to latest compatible versions`, so there is no stable semver-compatible Tauri refresh available to this lockfile that removes the GTK3/glib family.

Accordingly, the existing disposition is unchanged: do not force `glib >=0.20` into the GTK3 0.18 graph, do not suppress the advisories, and re-evaluate when upstream Tauri/Wry ships a supported GTK4/WebKit6 path or another compatible release changes this dependency family.

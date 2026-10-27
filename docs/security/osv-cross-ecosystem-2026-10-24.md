# OSV-Scanner 2.7.0 — full-source inventory (24 October 2026)

Source revision: main 5c8f68cedd48f85797efa934e0a1e8ed603c346f.

The recursive source scan extracted **seven dependency files**: the root Python
uv.lock and pnpm-lock.yaml, the Tauri Cargo.lock, three nested npm lockfiles,
and the KiCad plugin requirements file. **Result: five flagged Cargo packages
and zero reported PyPI/npm findings.** Exit code 1 means the scan is **NOT
clean**, even though the previously remediated pypdf, fastmcp and fast-uri
versions produced no OSV findings. GitHub's separate Dependabot Alerts API
still reported 15 older notices after those lockfile changes had merged;
their ingestion status must not be confused with live OSV matching.

| Cargo crate | Locked version | OSV IDs | Meaning |
| --- | --- | --- | --- |
| glib | 0.18.5 | RUSTSEC-2024-0429, GHSA-wrw7-89jp-8q8g | One unsoundness advisory with two aliases |
| proc-macro-error | 1.0.4 | RUSTSEC-2024-0370 | Unmaintained dependency |
| zbus_names | 4.3.4 | RUSTSEC-2026-0371 | Unmaintained; absorbed into zbus 6 |
| zvariant | 5.15.0 | RUSTSEC-2026-0370 | Unmaintained; absorbed into zbus 6 |
| zvariant_derive | 5.15.0 | RUSTSEC-2026-0372 | Unmaintained; absorbed into zbus 6 |

The five findings exactly match the already-reviewed and **unsuppressed**
GitHub security RustSec baseline, enforced by pinned cargo-audit in required
CI and on a weekly advisory-drift schedule. This new OSV result is **not
evidence that the old GTK and zbus dependencies are safe**. The application
does not directly call the affected glib VariantStrIter methods, but that is
not a proof of absence of transitive reachability. Related tracking:
[#1450](https://github.com/oaslananka/kicad-mcp-pro/issues/1450) and the
earlier [RustSec investigation](rustsec-gtk3-unic-disposition.md).

## Attempted corrections and compatibility blockers

Isolated-worktree Cargo solver attempts were made and discarded; Cargo.lock
was restored after each rejection.

- glib 0.18.5 -> 0.20.0 fails: GTK 0.18.2, brought in by stable Tauri
  2.12.2, requires glib ^0.18. glib patches this advisory in >=0.20.
- zbus 5.19.0 -> 6.1.0 fails: stable tauri-plugin-single-instance 2.5.4
  requires zbus ^5.9. zbus 6 is a major API migration, not a compatible
  lockfile-only patch.
- proc-macro-error has no patched release; it arrives through glib-macros
  0.18.5 and the existing Linux GTK stack.

Do not replace stable Tauri/GTK with unsupported alpha code or hide OSV
findings for cosmetic green status. Revisit when the upstream supported
stack migrates and then perform Linux, macOS, Windows and actual GUI
qualification before changing the production lock.

## Automated visibility

The OSV Full Dependency Inventory workflow uses the official **commit-pinned**
OSV-Scanner v2.7.0 scan and reporter Actions as explicit job steps on a weekly
schedule and on demand. The first merged reusable-workflow implementation
(#1451) could not create any GitHub Actions job (startup_failure, run
40103785911); the direct-step implementation isolates and avoids that
reusable workflow job-graph construction path.
It scans **all** repository-supported ecosystems, publishes SARIF into
GitHub Code Scanning, and does **not** configure any OSV ignore rules.

Its fail-on-vuln option is deliberately false, **only for the non-required
weekly observability job**, because the five upstream-blocked warnings would
otherwise fail every unchanged weekly run. A successful workflow means
the scanner executed; it **does not** mean the repository has no advisories.
The existing strict RustSec exact-baseline CI still rejects unreviewed
Rust advisories, and GitHub dependency-review policies remain unchanged.

No advisories were manually dismissed, no immutable Release setting was
changed, and no desktop runtime feature was disabled.


## Follow-up after GitHub alerts on 27 October 2026

Current baseline: main@b421e9f9b1e8469c46ab631464017b5f57644397.
The original 24 October summary remains archival, not the current Python inventory.

- New High-severity Dependabot alert #73 (GHSA-45c3-73f7-pv4m) identified
  dnspython 2.8.0, transitively required via
  kicad-sch-api -> fastmcp -> pydantic[email] -> email-validator.
  Regenerated uv.lock using the pinned uv resolver, upgrading dnspython to
  first patched version 2.9.0; added a regression floor test.
  Compatible patch refreshes for cryptography, joserfc, fastmcp and
  fastmcp-slim are included.
- Unsuppressed OSV-Scanner 2.7.0 inventory override at
  .github/security/osv-full-inventory.toml recursively examined seven
  lockfiles. Updated Python and npm lockfiles show no reported matches.
  The scan still exits 1: the existing five upstream-blocked RustSec packages
  remain plus block-buffer 0.10.4 (GHSA-qwgh-2vcv-g2f7; fixed >=0.12.1).
  The glib RustSec/GHSA aliases describe one root vulnerability.
- Newly confirmed block-buffer is indirect:
  tauri 2.12.2 -> tauri-macros 2.7.1 -> tauri-codegen 2.7.1 ->
  sha2 0.10.9 -> digest 0.10.7 -> block-buffer 0.10.4.
  Cargo rejected a dry-run requirement for 0.12.1 due to digest ^0.10.
  Forcing a new API version or moving the GUI to Tauri 3.x alpha would be
  an unverified breaking change and was NOT performed.
- Fresh Cargo solver checks reconfirm glib >=0.20 is incompatible with
  gtk 0.18.2 through supported Tauri 2.12.2 and zbus >=6 is incompatible
  with stable tauri-plugin-single-instance 2.5.4 requiring zbus ^5.9.
  The informational unmaintained notices have no patched standalone crates.
  Keep existing Rust warnings visible in weekly inventory and tracked
  under issue #1450.
- GitHub Scorecard code-scanning #53 cites BOTH dnspython and block-buffer.
  Fixing #73 removes only one Scorecard root cause; do not manually close #53
  or claim Scorecard clean without a newer main-branch scan.
- Updated the stale pinned OSV action SHA test to match the previously merged
  approved action bump (#1500). Workflow behavior was not modified.

Acceptance: merging this change and default-branch rescanning can fix
Dependabot alert #73. It does not resolve RustSec code scanning alerts or
Scorecard #53. Do not dismiss warnings, hide advisories or relax policy.

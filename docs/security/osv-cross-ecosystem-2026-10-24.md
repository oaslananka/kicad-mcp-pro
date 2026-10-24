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

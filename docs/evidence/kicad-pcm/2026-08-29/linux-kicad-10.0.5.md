# KiCad PCM Physical Linux Evidence

- Date: `2026-08-29`
- Product version: `3.33.3`
- Merged source revision: `c25b852d90321754a95199645a450be98b126e76`
- KiCad: `10.0.5`
- PCM artifact SHA-256: `e3d1016a47bf8c1270c79a13cb07e1084dcf4e18b8a39d0637841778584d87bd`
- PCM artifact size: `9,511` bytes
- Test content: repository fixture board only; no user project was mutated

## Reproducible package

The PCM ZIP was built twice from the final source tree and the two archives were
byte-for-byte identical. A later build from the merged revision on the authorized
Windows test host produced the same SHA-256 and size. That Windows result proves
cross-platform package reproducibility only; it is not recorded as a Windows
physical PCM installation result.

## Physical KiCad lifecycle

The exact package was installed through **Plugin and Content Manager -> Install
from File** on a real KiCad 10.0.5 Linux desktop. Installed companion files were
checked against the archive by hash. After a full KiCad restart, **Tools ->
External Plugins -> kicad-mcp companion** was discoverable.

The following states were exercised against fixture-safe content:

- backend stopped: fail-closed `backend_unreachable` guidance;
- compatible backend: live health reported backend `3.33.3`, IPC reachable, and
  live PCB context;
- MCP initialize: `serverInfo.version` reported the product version `3.33.3`;
- MCP lifecycle: initialize, initialized notification, tools/list,
  `kicad://studio/context`, and read-only `kicad_get_version`;
- healthy companion push: KiCad UI-thread return was approximately `0.0006 s`,
  while the backend completed `studio_push_context` successfully over HTTP 200;
- compatible reinstall/update: the same-version final candidate was reinstalled
  through PCM and the installed hashes matched the candidate archive;
- incompatible backend contract: fail-closed recovery guidance was shown and no
  context push was performed;
- uninstall: companion package/resources were removed while unrelated disposable
  client configuration remained unchanged;
- rollback: a previously trusted PCM artifact was reinstalled, discovered after
  restart, and then removed as part of host cleanup.

## Guided client transaction

A disposable Cursor project configuration was used to exercise the project-scoped
onboarding transaction. Preview did not mutate the file; explicit write targeted
the requested project, preserved unrelated keys/server entries, created a backup,
and restore returned the original file hash. This evidence is deliberately scoped
to the disposable Cursor flow and does not claim a physical Claude Code or Codex
application session.

## Host restoration

The KiCad API setting was enabled only for the live IPC portion of the test. After
verification, the pre-test KiCad configuration hashes were restored, the API was
disabled again, the PCM package/resources and IPC socket were removed, and the
temporary package copy was deleted.

## CI and quality evidence

PR #811 was merged as `c25b852d90321754a95199645a450be98b126e76`.
Before merge, the exact PR head passed Required PR Gate, full Python coverage, all
server/npm OS lanes, CodeQL, dependency review, Gitleaks, Semgrep, security,
SonarQube Cloud, and Codecov patch coverage. Sonar reported `0` new issues,
`96.8%` new-code coverage, and `0.0%` new-code duplication.

The merge revision then passed the exact-SHA push workflows including CI
(`33255537706`), SonarCloud (`33255537748`), CodeQL, Gitleaks, Scorecard, Docs,
Live Model Assurance, Release Please, and Dependency Graph.

## Remaining platform boundary

This evidence promotes only the Linux physical PCM path. Windows physical PCM flow
is still pending. The authorized Windows host reproduced the exact ZIP hash before
its remote-control session became unavailable, but no installation claim is made.
A physical macOS host is not currently available in the authorized device set;
macOS CI coverage is not treated as a substitute for a real PCM GUI lifecycle.

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
byte-for-byte identical. A later physical Windows run from the same merged revision
reproduced the same SHA-256 and size and completed the PCM lifecycle; see
[Windows physical evidence](windows-kicad-10.0.5.md).

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

## Guided client transaction and real client connect

A disposable Cursor project configuration was used to exercise the project-scoped
onboarding transaction. Preview did not mutate the file; explicit write targeted
the requested project, preserved unrelated keys/server entries, created a backup,
and restore returned the original file hash.

On the secondary Linux host, Claude Code `2.1.238` was exercised as a real supported
MCP client while KiCad `10.0.5` and the loopback backend were live. The test used a
temporary `HOME` and disposable project, added the `kicad` server with Claude's own
`mcp add --scope local --transport http` command, then ran `claude mcp get kicad`.
Claude reported `Status: Connected` for `http://127.0.0.1:3334/mcp`; the backend
recorded the corresponding initialize/session traffic.
The user Claude configuration was not modified. MCP initialize/list-tools and the read-only `kicad_get_version`
tool call were independently verified in the physical KiCad lifecycle smoke above.

## Host restoration

The KiCad API setting was enabled only for the live IPC portion of the test. After
verification, the pre-test KiCad configuration hashes were restored, the API was
disabled again, the PCM package/resources and IPC socket were removed, and the
temporary package copy was deleted.

## Secondary physical Linux host

A second authorized Linux desktop (`msi`) independently exercised the same merged
revision and KiCad `10.0.5`. Its final PCM build reproduced the same
`e3d1016a47bf8c1270c79a13cb07e1084dcf4e18b8a39d0637841778584d87bd`
artifact hash and `9,511`-byte size. The host already had an older trusted
`3.33.3` companion candidate installed, so this run exercised the real PCM update
path rather than a clean first install.

The final candidate replaced the installed companion through PCM and all installed
plugin/resource hashes matched the final archive. After restart, the companion was
discovered in PCB Editor. Backend-down guidance failed closed; with the exact merged
backend, live health reported KiCad IPC and PCB context available. The companion
returned from the KiCad UI thread in approximately `0.000133 s`, while
`studio_push_context` completed in `2.483 ms` with HTTP 200. MCP initialize returned
`serverInfo.version=3.33.3`; initialized, tools/list (`24` tools),
`kicad://studio/context`, and read-only `kicad_get_version` all succeeded against the
disposable fixture board. Forced backend incompatibility also failed closed, with an
approximately `0.000068 s` UI-thread return.

PCM uninstall was committed with **Apply Pending Changes**; plugin/resources were
removed and a disposable unrelated client-config hash remained unchanged. Rollback
then reinstalled the host's pre-test trusted PCM artifact with SHA-256
`08b112d870f412a0e55c0f15f60264726e3cdd4ebc0e30768888d53a8b37a8c6`;
its installed file hashes matched that archive and restart rediscovered the companion.
Finally, the captured KiCad config and user-share trees were restored to their exact
pre-test tree hashes. The user's active repository branch and dirty working tree were
unchanged by the evidence run.

This is a second independent Linux-host result. It strengthens Linux physical
confidence but does not change the Windows/macOS platform boundary below.

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

This file records the Linux physical PCM path. Windows physical PCM lifecycle is now
separately verified in [Windows physical evidence](windows-kicad-10.0.5.md).
A physical macOS host is not currently available in the authorized device set;
macOS CI coverage is not treated as a substitute for a real PCM GUI lifecycle.

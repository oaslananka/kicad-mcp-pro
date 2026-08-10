# Dependency Management

KiCad MCP Pro uses reviewable dependency declarations, lockfiles, audit jobs, and pinned release infrastructure to reduce supply-chain risk.

## Dependency sources

| Ecosystem | Primary files | Policy |
| --- | --- | --- |
| Python | `pyproject.toml`, `uv.lock` | Use `uv` lockfiles and review dependency updates through pull requests. |
| Node / npm / pnpm | `package.json`, `pnpm-lock.yaml`, package-level lockfiles | Use lockfiles and Corepack-managed package managers. |
| Docker | `Dockerfile` | Pin base images by digest and avoid unpinned package-manager bootstrap steps. |
| GitHub Actions | `.github/workflows/*.yml` | Pin third-party Actions to full commit SHAs and keep job permissions minimal. |
| Rust / Tauri | Cargo manifests and lockfiles where present | Keep generated lockfiles under version control when used for release artifacts. |

## Automated update ownership

GitHub Dependabot is the single normal dependency-update source for this repository.
`.github/dependabot.yml` covers the root `uv` project, npm/pnpm package locations,
GitHub Actions, Docker/Docker Compose, and the Tauri Cargo project. Renovate is not
part of the active update path, so the repository does not keep a second bot
configuration that could create duplicate update pull requests.

Dependabot runs weekly on Monday using the repository's Europe/Istanbul maintenance
window. Routine minor/patch version updates are grouped per ecosystem and package-manager
boundary to reduce PR and CI churn; major updates remain individual pull requests. The
npm/pnpm configuration uses separate single-directory entries for the root pnpm project,
the ChatGPT Apps npm project, the fixture pnpm package, and the npm wrapper so Dependabot
does not mix independent lockfile/workspace scopes in one update job. Docker version
automation is more conservative: only patch updates are grouped, leaving runtime-sensitive
image minor/major changes for explicit maintainer review. Security updates use separate
groups and are never mixed with routine version-update groups.

Dependabot pull requests are ordinary protected pull requests: required CI and the
`main` ruleset still apply, and no dependency bot is allowed to bypass those gates.
Mergify provides a serial, one-PR-at-a-time queue for the routine grouped version
updates only. The queue explicitly mirrors every required status-check context from
`.github/rulesets/main.json`. Eligibility and required-check conditions are identical at
queue and merge time so strict up-to-date rulesets use Mergify's in-place check model
instead of a second draft-PR CI phase. Automatic GitHub ruleset discovery is
defense-in-depth rather than the enforcement source. Repository regression tests prevent
ruleset/check or queue/merge-condition drift. The queue uses squash merges and does not
retry failed checks automatically.
Human-authored, release, security, major, and otherwise ungrouped dependency pull
requests remain a maintainer decision.

## Lockfile maintenance

When a supported dependency update changes resolution, Dependabot updates the matching
manifest and lockfile together where the ecosystem supports it. The tracked lockfiles
remain authoritative build inputs:

- Python: `pyproject.toml` + `uv.lock`;
- pnpm/npm: `package.json` + `pnpm-lock.yaml` or the package-local `package-lock.json`;
- Rust/Tauri: `src-tauri/Cargo.toml` + `src-tauri/Cargo.lock`.

Lockfile-only refreshes that are not caused by an available dependency version are a
maintainer task and must use the repository's pinned toolchain. CI uses frozen/locked
installs and therefore rejects stale or unexpectedly regenerated lockfiles.

## Update process

1. Dependabot opens either a routine ecosystem group or an individual higher-risk dependency pull request from the default branch.
2. Review the dependency source, package name, version change, release notes, and license impact.
3. Run the required CI, security checks, tests, and relevant package builds.
4. Confirm the matching lockfile changed only as expected.
5. Routine grouped minor/patch version updates may enter the Mergify queue automatically; the GitHub ruleset and required checks remain mandatory.
6. Security, major, runtime-sensitive, release, human-authored, and ungrouped updates require an explicit maintainer merge decision.

## Vulnerability monitoring

Dependabot alerts and Dependabot security updates own automated vulnerable-dependency
remediation. Dependency audit scripts, CodeQL, Gitleaks, Trivy, and Scorecard provide
additional detection and policy evidence. Security-sensitive updates should be
prioritized according to [`SECURITY.md`](https://github.com/oaslananka/kicad-mcp-pro/blob/main/SECURITY.md).

## Vendoring and generated code

Vendored code and generated artifacts should be avoided unless there is a clear release or interoperability reason. If unavoidable, document:

- upstream source and version;
- license;
- update procedure;
- verification command;
- reason the dependency cannot be consumed through normal package management.

## Release dependency evidence

Release workflows should produce SBOMs, checksums, and provenance evidence when supported by the artifact class. See [`../security/release-security.md`](../security/release-security.md) and [`../security/release-integrity.md`](../security/release-integrity.md).

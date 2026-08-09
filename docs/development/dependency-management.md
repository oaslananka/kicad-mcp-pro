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
window. Its pull requests are ordinary protected pull requests: required CI and the
`main` ruleset still apply, and no dependency bot is allowed to bypass those gates.

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

1. Dependabot opens a focused dependency pull request from the default branch.
2. Review the dependency source, package name, version change, release notes, and license impact.
3. Run the required CI, security checks, tests, and relevant package builds.
4. Confirm the matching lockfile changed only as expected.
5. Merge only after required checks pass; major/runtime-sensitive updates receive maintainer review.

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

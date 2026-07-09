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

## Update process

1. Open a focused PR for dependency updates.
2. Explain the dependency source, package name, version change, and reason.
3. Run CI, security checks, tests, and relevant package builds.
4. Review changelogs for breaking changes, licensing changes, and known vulnerabilities.
5. Regenerate lockfiles and release metadata when required.
6. Merge only after required checks pass.

## Vulnerability monitoring

The repository uses GitHub Dependabot, dependency audit scripts, CodeQL, Gitleaks, Trivy, and Scorecard. Security-sensitive updates should be prioritized according to [`SECURITY.md`](https://github.com/oaslananka/kicad-mcp-pro/blob/main/SECURITY.md).

## Vendoring and generated code

Vendored code and generated artifacts should be avoided unless there is a clear release or interoperability reason. If unavoidable, document:

- upstream source and version;
- license;
- update procedure;
- verification command;
- reason the dependency cannot be consumed through normal package management.

## Release dependency evidence

Release workflows should produce SBOMs, checksums, and provenance evidence when supported by the artifact class. See [`../security/release-security.md`](../security/release-security.md) and [`../security/release-integrity.md`](../security/release-integrity.md).

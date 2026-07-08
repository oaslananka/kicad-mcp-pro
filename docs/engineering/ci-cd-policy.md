# CI/CD Policy — Path-Aware Risk-Based Gating

> **Status**: Active
> **Last updated**: 2026-07-08

## Overview

This repository uses **path-aware CI/CD gating** to run the right checks for
each pull request based on which files changed. The goals are:

1. **Minimize unnecessary compute** — docs-only PRs should not wait for full
   OS-matrix CI, CodeQL, or package builds.
2. **Maintain security posture** — secret scanning always runs; code analysis
   runs on code changes; dependency review runs when lockfiles change.
3. **Never break required checks** — all branch-protection required checks
   report a status (success via no-op or full run) on every PR.
4. **Keep release workflows safe** — real publish only happens on release/tag
   events with environment protection, OIDC, attestation, and cosign.

## Change Categories

Each PR is classified by the files it touches. A PR can belong to multiple
categories.

| Category | File Patterns |
|----------|--------------|
| **docs** | `docs/**`, `README.md`, `CONTRIBUTING.md`, `CHANGELOG.md`, `CODE_OF_CONDUCT.md`, `GOVERNANCE.md`, `MAINTAINERS.md`, `ROADMAP.md`, `SECURITY.md`, `SUPPORT.md`, `ARCHITECTURE.md`, `CITATION.cff`, `LICENSE`, `mkdocs.yml`, `assets/**` |
| **python** | `src/**`, `tests/**`, `pyproject.toml`, `uv.lock`, `uv.toml`, `scripts/**`, `conftest.py`, `pyrightconfig.json`, `.python-version`, `performance/**`, `evals/**` |
| **npm** | `packages/**`, `package.json`, `pnpm-lock.yaml`, `pnpm-workspace.yaml`, `.node-version`, `.npmrc`, `commitlint.config.cjs`, `.commitlintrc.json` |
| **schemas** | `packages/protocol-schemas/**` |
| **workflows** | `.github/workflows/**`, `.github/actions/**` |
| **dependencies** | `package.json`, `pnpm-lock.yaml`, `pyproject.toml`, `uv.lock`, `Dockerfile`, `renovate.json` |
| **release** | `.release-please-manifest.json`, `release-please-config.json`, `server.json`, `Dockerfile`, `docker-entrypoint.sh`, `docker-compose.yml` |
| **kicad** | `src/kicad_mcp/tools/schematic*.py`, `src/kicad_mcp/tools/pcb*.py`, `tests/integration/**`, `tests/fixtures/**`, `scripts/kicad_canary.py`, `compatibility.yaml`, `test-fixtures/**` |

A PR is classified as **docs-only** when it touches files in the `docs`
category and does _not_ touch files in `python`, `npm`, `schemas`,
`workflows`, or `dependencies`. The `dependencies` exclusion matters: a PR
that edits `README.md` alongside `Dockerfile` or a lockfile must **not** be
treated as docs-only, or the Trivy filesystem scan (in the `security` job)
would incorrectly no-op on a real dependency/Dockerfile change.

## Workflow Behavior by PR Type

| Job / Check | Docs-only PR | Python PR | NPM PR | Schema PR | Workflow PR | Full / Mixed PR |
|-------------|:------------:|:---------:|:------:|:---------:|:-----------:|:---------------:|
| `mcp-server` (3 OS) | no-op ✅ | **full** | no-op ✅ | no-op ✅ | **full** | **full** |
| `mcp-npm` (3 OS) | no-op ✅ | no-op ✅ | **full** | no-op ✅ | **full** | **full** |
| `protocol-schemas` | no-op ✅ | **full** | **full** | **full** | **full** | **full** |
| `scan` (Gitleaks) | **full** | **full** | **full** | **full** | **full** | **full** |
| `analyze` (CodeQL) | no-op ✅ | **full** | **full** | **full** | **full** | **full** |
| Dependency Review | not triggered | if deps ∆ | if deps ∆ | not triggered | if workflow file ∆ | if deps ∆ |
| `required-pr-gate` | ✅ pass | ✅ pass/fail | ✅ pass/fail | ✅ pass/fail | ✅ pass/fail | ✅ pass/fail |

**no-op** means the job runs and reports success, but skips expensive steps.
This ensures the required status check is never left pending.

Dependency Review is scoped at the **workflow trigger** level (`on.pull_request.paths`
in `dependency-review.yml`), not via the `changes` job, so it does not run at
all (no check appears) unless the PR touches `package.json`, `pnpm-lock.yaml`,
`pyproject.toml`, `uv.lock`, `Dockerfile`, `renovate.json`,
`packages/mcp-npm/package.json`/`package-lock.json`, or the workflow file
itself. This is safe only because Dependency Review is **not** a required
status check.

## Required Status Checks

The following checks are required by the `main` branch ruleset and must report
a status on every PR:

| # | Check Name | Source Workflow | Source Job |
|---|-----------|---------------|-----------|
| 1 | `mcp-server (ubuntu-24.04)` | `ci.yml` | `mcp-server` |
| 2 | `mcp-server (windows-2025)` | `ci.yml` | `mcp-server` |
| 3 | `mcp-server (macos-15)` | `ci.yml` | `mcp-server` |
| 4 | `mcp-npm (ubuntu-24.04)` | `ci.yml` | `mcp-npm` |
| 5 | `mcp-npm (windows-2025)` | `ci.yml` | `mcp-npm` |
| 6 | `mcp-npm (macos-15)` | `ci.yml` | `mcp-npm` |
| 7 | `protocol-schemas` | `ci.yml` | `protocol-schemas` |
| 8 | `scan` | `gitleaks.yml` | `scan` |
| 9 | `analyze (python)` | `codeql.yml` | `analyze` |
| 10 | `analyze (javascript-typescript)` | `codeql.yml` | `analyze` |

### Step-Level No-Op Pattern

To ensure required checks always report success even on docs-only PRs, we use
**step-level no-op** rather than job-level `if:` skip:

1. The job always runs (so GitHub receives a status).
2. The first step checks the change detection outputs.
3. If the PR is docs-only and the job is not needed, it prints a notice and
   sets an environment variable to skip remaining steps.
4. All subsequent steps have `if: env.docs_only != 'true'`.

This avoids the "pending check" problem that occurs when a required job is
skipped entirely.

### Aggregate Gate (`required-pr-gate`)

`ci.yml` includes a `required-pr-gate` job that evaluates the results of
`changes`, `mcp-server`, `mcp-npm`, `protocol-schemas`, and `security`,
failing on any `failure`/`cancelled` result and passing on `success`/`skipped`.
It exists to let branch protection eventually depend on **one** check instead
of pinning every individual matrix context, so job renames or new matrix
entries don't require a ruleset edit.

**As of this writing it is not yet part of the branch ruleset.** The required
migration sequence, in order:

1. Merge the `required-pr-gate` job to `main`.
2. Confirm it appears and reports correctly on a fresh PR built from updated `main`.
3. Additively add `Required PR Gate` to ruleset `18233373`'s required checks
   (keep the existing 10 contexts — do not remove them yet).
4. As a separate, explicitly-labeled follow-up, once confidence is established,
   remove the 7 matrix-specific contexts (`mcp-server (*)`, `mcp-npm (*)`,
   `protocol-schemas`), leaving `Required PR Gate` + `scan` +
   `analyze (python)` + `analyze (javascript-typescript)`.

Adding step 3 before step 1/2 would create an unsatisfiable pending check on
every already-open PR that doesn't yet contain the job — this is exactly the
"required check pending" failure mode this whole policy exists to avoid.

## Security Workflows

| Workflow | Runs on docs-only PR? | Rationale |
|----------|:---------------------:|-----------|
| **Gitleaks** (`scan`) | ✅ Always | Fast; secrets can appear in any file. |
| **CodeQL** (`analyze`) | no-op | Code analysis is irrelevant for docs changes. Scheduled full scan runs weekly regardless. |
| **Dependency Review** | Not triggered (no lockfile/manifest changes) | Only meaningful when dependency files change; scoped via workflow-level `paths:`, not a `changes` output. |
| **Scorecard** | Not triggered on PR | Runs on push to main and weekly schedule. |
| **Trivy** (in CI `security` job) | no-op on docs-only | Filesystem vulnerability scan is code-focused. |
| **SonarQube Cloud** | Runs (Automatic Analysis, not workflow-gated) | Not a required check; see below for scope. |

### Dependency Graph and Renovate

GitHub's Dependency Graph (`vulnerability-alerts` API) is **enabled** on this
repository. It must be enabled for the Dependency Review action to function
at all — without it, Dependency Review fails on every PR regardless of path
filtering, with the error "Dependency review is not supported on this
repository."

`renovate.json` already exists at the repo root and is well-configured
(`config:best-practices`, `security:openssf-scorecard`, `pinDigests` for
GitHub Actions and Docker, `vulnerabilityAlerts` + `osvVulnerabilityAlerts`).
It currently has no effect because the Mend Renovate GitHub App is not
installed on this repository/org — installing the app is the only remaining
step to activate it; `dependabot.yml` is intentionally left disabled in favor
of it.

### SonarQube Cloud scope

This project has no Sonar CI workflow — it runs under SonarQube Cloud's
**Automatic Analysis** mode, which reads `.sonarcloud.properties` from the
default branch (a different file from the `sonar-project.properties` format
used by CI-based scans; if both existed, Automatic Analysis would ignore its
own settings and fall back to the properties file, so only one may be
present). `.sonarcloud.properties` sets `sonar.tests` to classify `tests/`,
`packages/protocol-schemas/test/`, and `packages/kicad-fixtures/test/` as
test code. This only affects path classification — it does not exclude any
file from analysis, and it does not change rule severities or Quality
Profiles (those require SonarQube Cloud UI/admin access, not a repo file).
Sonar is not a required status check, so it cannot block merges either way.

## Publish Workflows

All publish workflows enforce strict safety:

- **Trigger**: Only `release` (published) or `workflow_dispatch` with explicit
  inputs.
- **PR context**: Dry-run only (build without push, validate without publish).
- **Environment protection**: `pypi`, `testpypi`, `npm`, `mcp-registry`
  environments with approval rules.
- **Supply chain**: OIDC trusted publishing, attestation, SBOM generation,
  SHA256 checksum verification, cosign signing.
- **Idempotency**: All publish jobs check if the version is already published
  before attempting to publish.

| Workflow | PR Behavior | Release Behavior |
|----------|------------|-----------------|
| Publish Python | N/A | Build → attest → publish to PyPI with OIDC |
| Publish npm | N/A | Pack → attest → publish with provenance |
| Publish Container | Dry-run build (cacheonly) | Push to GHCR → Trivy scan → cosign sign |
| Publish MCP Registry | Dry-run validate | Wait for artifacts → publish to registry |
| Publish Protocol Schemas | N/A | Build → attest → publish to npm |
| GUI Release | N/A | Build Tauri → create GitHub Release |

## Supply Chain — Action Pinning

Every third-party action reference across `.github/workflows/` is pinned to a
commit SHA (not a mutable tag like `@v4` or `@main`). This is verified by:

```
grep -rnE "uses:.*@(v[0-9]|main|master)" .github/workflows/ | grep -vE "@[0-9a-f]{40}"
```

returning no output. When bumping a pinned action, resolve the new tag to its
commit SHA and reuse the same SHA across every workflow that references that
action, to keep pins consistent repo-wide.

## Rollback

Path-aware gating can be fully reverted by:

1. Removing the `changes` job from `ci.yml`.
2. Removing `needs: changes` from downstream jobs.
3. Removing `if:` conditions on no-op steps.

This restores the original behavior where all jobs run unconditionally on every
PR. No branch protection changes are needed for rollback.

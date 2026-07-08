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
category and does _not_ touch files in `python`, `npm`, `schemas`, or
`workflows`.

## Workflow Behavior by PR Type

| Job / Check | Docs-only PR | Python PR | NPM PR | Schema PR | Workflow PR | Full / Mixed PR |
|-------------|:------------:|:---------:|:------:|:---------:|:-----------:|:---------------:|
| `mcp-server` (3 OS) | no-op ✅ | **full** | no-op ✅ | no-op ✅ | **full** | **full** |
| `mcp-npm` (3 OS) | no-op ✅ | no-op ✅ | **full** | no-op ✅ | **full** | **full** |
| `protocol-schemas` | no-op ✅ | **full** | **full** | **full** | **full** | **full** |
| `scan` (Gitleaks) | **full** | **full** | **full** | **full** | **full** | **full** |
| `analyze` (CodeQL) | no-op ✅ | **full** | **full** | **full** | **full** | **full** |
| Dependency Review | skip | if deps ∆ | if deps ∆ | skip | **full** | if deps ∆ |

**no-op** means the job runs and reports success, but skips expensive steps.
This ensures the required status check is never left pending.

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

## Security Workflows

| Workflow | Runs on docs-only PR? | Rationale |
|----------|:---------------------:|-----------|
| **Gitleaks** (`scan`) | ✅ Always | Fast; secrets can appear in any file. |
| **CodeQL** (`analyze`) | no-op | Code analysis is irrelevant for docs changes. Scheduled full scan runs weekly regardless. |
| **Dependency Review** | Skip if no lockfile/manifest changes | Only meaningful when dependency files change. |
| **Scorecard** | Not triggered on PR | Runs on push to main and weekly schedule. |
| **Trivy** (in CI `security` job) | no-op on docs-only | Filesystem vulnerability scan is code-focused. |

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

## Rollback

Path-aware gating can be fully reverted by:

1. Removing the `changes` job from `ci.yml`.
2. Removing `needs: changes` from downstream jobs.
3. Removing `if:` conditions on no-op steps.

This restores the original behavior where all jobs run unconditionally on every
PR. No branch protection changes are needed for rollback.

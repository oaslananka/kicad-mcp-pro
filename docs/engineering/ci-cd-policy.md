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
| **dependencies** | `package.json`, `pnpm-lock.yaml`, `pyproject.toml`, `uv.lock`, `Dockerfile`, `.github/dependabot.yml` |
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
| `CI Tests / Coverage` | no-op ✅ | **full** | no-op ✅ | no-op ✅ | **full** | **full** |
| `mcp-npm` (3 OS) | no-op ✅ | no-op ✅ | **full** | no-op ✅ | **full** | **full** |
| `protocol-schemas` | no-op ✅ | **full** | **full** | **full** | **full** | **full** |
| `scan` (Gitleaks) | **full** | **full** | **full** | **full** | **full** | **full** |
| `analyze` (CodeQL) | no-op ✅ | **full** | **full** | **full** | **full** | **full** |
| Dependency Review | **full** | **full** | **full** | **full** | **full** | **full** |
| `required-pr-gate` | ✅ pass | ✅ pass/fail | ✅ pass/fail | ✅ pass/fail | ✅ pass/fail | ✅ pass/fail |

**no-op** means the job runs and reports success, but skips expensive steps.
This ensures the required status check is never left pending.

Dependency Review runs on every pull request to `main` and is a required
status check. It must not be path-filtered at the workflow trigger because a
missing required context would leave an otherwise valid pull request blocked.
The action itself reports success when a pull request has no dependency-graph
delta.

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
`changes`, `mcp-server`, `coverage`, `mcp-npm`, `protocol-schemas`, and `security`,
failing on any `failure`/`cancelled` result and passing on `success`/`skipped`.
It exists to let branch protection eventually depend on **one** check instead
of pinning every individual matrix context, so job renames or new matrix
entries don't require a ruleset edit.

`Required PR Gate` is active in ruleset `18233373`. The existing operating-
system matrix, protocol schema, secret scan, CodeQL, and dependency-review
contexts remain required alongside it. New internal jobs such as `coverage`
become merge-blocking by joining the aggregate gate; they should not be added
directly to the ruleset until they have a stable history and a deliberate
migration plan.

### Codecov reporting

`CI Tests / Coverage` is the recognized full-test summary check for OpenSSF
Scorecard and the source of Codecov Python coverage and JUnit test analytics.
It authenticates with OIDC and runs upload steps after failed tests. Codecov
project and patch statuses use relative `auto` targets and are informational
during baseline collection; the pytest failure and 83% local coverage threshold
remain blocking through the
aggregate gate.

## Security Workflows

| Workflow | Runs on docs-only PR? | Rationale |
|----------|:---------------------:|-----------|
| **Gitleaks** (`scan`) | ✅ Always | Fast; secrets can appear in any file. |
| **CodeQL** (`analyze`) | no-op | Code analysis is irrelevant for docs changes. Scheduled full scan runs weekly regardless. |
| **Dependency Review** | ✅ Always | Required context; evaluates dependency-graph changes and succeeds when no dependency delta exists. |
| **Scorecard** | Not triggered on PR | Runs on push to main and weekly schedule. |
| **Trivy** (in CI `security` job) | no-op on docs-only | Filesystem vulnerability scan is code-focused. |
| **SonarQube Cloud** | Runs (Automatic Analysis, not workflow-gated) | Not a required check; see below for scope. |

### Dependency Graph and Dependabot

GitHub's Dependency Graph (`vulnerability-alerts` API) is **enabled** on this
repository. It must stay enabled for Dependency Review and Dependabot alerts.

`.github/dependabot.yml` is the active dependency-update configuration. It covers
`uv`, npm/pnpm package locations, GitHub Actions, Docker/Docker Compose, and Cargo.
Dependabot security updates own automated vulnerable-dependency remediation. The
repository intentionally has no active Renovate configuration or Mend Renovate App
requirement, avoiding two bots opening overlapping update pull requests.

Dependabot update PRs use the same protected-branch path as maintainer PRs. Routine
minor/patch version updates are grouped per ecosystem, while major and runtime-sensitive
updates remain individually reviewable and security updates use separate groups.
Required status checks and the active `main` ruleset remain authoritative; neither
Dependabot nor Mergify bypasses them. Mergify may automatically queue only the explicitly
allowlisted routine Dependabot groups, one PR at a time. Its merge conditions explicitly
mirror the required contexts declared in `.github/rulesets/main.json`; repository tests
require an exact match, so Mergify does not rely on external ruleset-discovery APIs to
decide that CI is complete. Human, release, security, major, and other ungrouped PRs are
not auto-queued by repository policy.

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

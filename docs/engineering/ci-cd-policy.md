# CI/CD Policy — Path-Aware Risk-Based Gating

> **Status**: Active
> **Last updated**: 2026-10-07

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
| **repo_tooling** | `package.json`, `pnpm-workspace.yaml`, `Dockerfile`, `docker-compose.yml`, `lefthook.yml`, `.pre-commit-config.yaml`, `Taskfile.yml`, `.mergify.yml`, `.github/dependabot.yml`, `.github/rulesets/**`, `sonar-project.properties`, `AGENTS.md`, `**/AGENTS.md` |
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
| `Python changed-file quality` | no-op ✅ | **changed-file Ruff** | no-op ✅ | no-op ✅ | no-op ✅ | **when Python changes** |
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

Repository-tooling contracts are an explicit exception to the generic NPM no-op row above.
Changes to root hook/tooling and repository-policy inputs such as `package.json`,
`pnpm-workspace.yaml`, `Dockerfile`, `docker-compose.yml`, `lefthook.yml`,
`.pre-commit-config.yaml`, `Taskfile.yml`, `.mergify.yml`, Dependabot/ruleset
configuration, `sonar-project.properties`, or `AGENTS.md` force the `mcp-server`
OS matrix and full Python coverage lane to run their real unit/tooling-contract suite.
This prevents a required check from reporting a no-op success when Python tests consume a
non-Python repository contract.

The internal `Python changed-file quality` job reuses `scripts/hook_pre_push.py`
in `--ruff-only` mode against the exact pull-request/push diff. The shared selector
keeps maintained Python files under `src/`, `tests/`, and `scripts/` aligned between
local pre-push and remote CI while avoiding unrelated legacy-script cleanup. It joins
the aggregate `Required PR Gate` rather than becoming a new branch-protection context.

Dependency Review runs on every pull request to `main` and is a required
status check. It must not be path-filtered at the workflow trigger because a
missing required context would leave an otherwise valid pull request blocked.
The action itself reports success when a pull request has no dependency-graph
delta.

### Primary Linux KiCad 10.0.7 native PR canary (current stable)

The `KiCad Live E2E` workflow contains `kicad-10-0-7-primary-canary`
for relevant PR changes, on Ubuntu 24.04. It validates an **exact SHA-256
pinned KiCad 10.0.7 lite AppImage** plus a separate SHA-256 verified KiCad
10.0.7 symbol-library source archive, packed with KiCad's own CMake tooling,
before the **32-step native CLI canary** and semantic comparisons. The installer
checks both the tarball and extracted AppImage digests before executing code,
requires the exact CLI version, and exports the scoped CLI/symbol paths for
native tools and the schematic parser. The libraries are required because the
bundled KiCad archive contains unpacked `.kicad_symdir` symbols while the
repository's schematic parser reads packed `.kicad_sym` libraries.

Both tarball hashes are based on explicitly reviewed downloaded bytes. They
are fixed, not dynamically scraped. This is **content integrity**, not
independent vendor signature verification or universal supply-chain approval.
The artifacts originate from the KiCad mirrors and upstream symbol GitLab
repository, rather than the intermittently unavailable Launchpad PPA. A
checksum mismatch, unavailable download, missing asset, or wrong CLI version
fails closed; there is no fallback to another KiCad version.

The historical Ubuntu 22.04 **10.0.6** KiCad Live E2E canary remains available
on main pushes, scheduled runs and manual dispatch, but **skips PR events**.
The 10.0.6 development-bootstrap canary is manual only. This prevents repair
of an obsolete version-specific CI environment from blocking current-stable
engineering changes. Neither of these optional jobs is a release approval or
a bypass of compatibility policy.

This change does **not** silently promote `kicad.latestVerified` or the
existing feature-parity baseline. Those require their own exact-source,
platform-scoped patch/IPC/GUI evidence and explicit acceptance. The new
primary canary is a non-required PR check until branch protection is separately
reviewed and changed; its CI result must not be represented as a required
branch protection condition without that operation.

### Windows 10.0.7 bounded native qualification (non-required)

`kicad-10-0-7-windows-qualification.yml` runs the **native CLI** suite on
`windows-2025` after selected `main` pushes and on a weekly Tuesday 05:17 UTC
schedule; maintainers can also dispatch it manually. It deliberately has **no**
`pull_request`, `pull_request_target`, or `workflow_run` event, is **not** a
branch-protection context, and does not introduce a new required PR check.
The path filter covers the KiCad canary implementation, differential/PCB/
export/validation/tool adapters, fixtures, and locked dependencies so ordinary
documentation or unrelated package changes do not download the large installer.
Scheduled events always execute the default branch. Separate concurrency groups
for `push`, `schedule`, and `workflow_dispatch` keep unattended runs from
coalescing with explicitly operator-dispatched runs; running jobs are not
force-cancelled. GitHub may replace an older pending event in a group.

Every run uses an ephemeral GitHub-hosted Windows runner, read-only token,
credential-free checkout, SHA-pinned third-party Actions, a bounded download
from official KiCad mirrors, an independently reviewed **fixed SHA-256**,
Authenticode signer validation, an isolated installer directory, exact CLI
version, the 32-step native canary/5 semantic comparisons, limited artifact
retention and `always()` cleanup. No repository secrets or elevated publishing
identity are passed to the checked-out source. The interactive **GUI/IPC**
workflow is **operator-only** and never launched by this automation.

This is a *post-merge and scheduled qualification signal*, not evidence that
KiCad 10.0.7 is supported on every platform, not a replacement for the
Ubuntu 22.04 legacy 10.0.6 lane, and not authorization to modify
`kicad.latestVerified`, autonomous manufacturing evidence or release policy.
If it is ever promoted to a mandatory pre-merge check, review PR/fork trust,
runner minutes, always-reporting branch-protection contexts, Mergify conditions,
and ruleset/documentation together as a separate change. Track promotion in
[#1181](https://github.com/oaslananka/kicad-mcp-pro/issues/1181).

## Required Status Checks

The following checks are required by the `main-standard` branch ruleset and must report
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
| 11 | `Required PR Gate` | `ci.yml` | `required-pr-gate` |
| 12 | `SonarCloud Scan` | `ci.yml` | `sonarcloud` |
| 13 | `dependency-review` | `dependency-review.yml` | `dependency-review` |

`Live Model Release Policy` is intentionally **not** a main-ruleset PR context. `live-model-assurance.yml` runs protected provider smoke after main pushes, while `release.yml` enforces deterministic live-model release readiness on release-please PRs and published releases. A missing, stale, or contract-mismatched approved baseline blocks that release boundary until the protected full gate promotes reviewed evidence.

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

### One-run Python coverage for SonarCloud

The required `SonarCloud Scan` is produced by `ci.yml` after `CI Tests / Coverage`.
For Python or workflow changes, the authoritative 83% full-suite and 90% changed-line
coverage checks run once. A report is uploaded as an ephemeral, run-local artifact
only after those checks pass. The Sonar job downloads it from **that same workflow
run**, verifies the exact merge-commit SHA, run ID, run attempt and report digest,
and then performs static analysis. The required check's name remains unchanged.

When CI legitimately skips full Python coverage for non-Python changes, but
Sonar still needs code analysis, the same trusted Sonar job executes the shared
full-suite action as a fallback. Release-metadata-only changes, docs-only changes,
fork pull requests, and Dependabot PRs retain explicit Sonar no-op handling.
`sonarcloud.yml` remains available for **manual fallback diagnostics only**, not
as a second pull-request workflow producing a duplicate required check.

A failed Python full suite or patch-coverage gate always blocks the `Required PR
Gate`, and is never replaced with an apparent successful Sonar report. Coverage
artifacts are only exchanged within one workflow run; cross-workflow artifact
reuse and untrusted PR credential promotion remain disallowed.

### Aggregate Gate (`required-pr-gate`)

`ci.yml` includes `required-pr-gate`, which collects all mandatory job
results and fails closed on `failure`, `cancelled`, unknown results and
**unexpected `skipped`**. Only two skips are permitted at the aggregate job
level: `changes` on an explicit manual dispatch, and `release-readiness` for
a non-release-please event. Other path-aware test work is skipped **within**
its job so GitHub always receives a successful required status. The aggregate
step summary now records a rationale for every outcome.

For normal pull requests, CI concurrency cancels a superseded commit to
conserve runner minutes. On `main` pushes the concurrency key includes the
exact Git SHA and does **not** cancel ongoing post-merge CI evidence; every
merge receives its own immutable validation result. This is a conscious
tradeoff between complete main evidence and additional runner usage.

`Required PR Gate` is active in the `main-standard` ruleset. The existing operating-
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
| **SonarQube Cloud** | Runs for trusted same-repository PRs; conditionally skips Dependabot/forks | Required as `SonarCloud Scan`; see below for skip semantics. |

### Dependency Graph and Dependabot

GitHub's Dependency Graph (`vulnerability-alerts` API) is **enabled** on this
repository. It must stay enabled for Dependency Review and Dependabot alerts.

`.github/dependabot.yml` is the active dependency-update configuration. It covers
`uv`, npm/pnpm package locations, GitHub Actions, Docker/Docker Compose, and Cargo.
Dependabot security updates own automated vulnerable-dependency remediation. The
repository intentionally has no active Renovate configuration or Mend Renovate App
requirement, avoiding two bots opening overlapping update pull requests.

Dependabot update PRs use the same protected-branch path as maintainer PRs. Routine
minor/patch version updates are grouped per ecosystem and package-manager boundary, while
major and runtime-sensitive updates remain individually reviewable and security updates
use separate groups. npm/pnpm update entries stay single-directory so independent pnpm
workspace and npm lockfile scopes are never combined into one Dependabot updater job.

Routine version-update scans are staggered across Monday through Friday in the
Europe/Istanbul maintenance window, with separate morning/noon slots where a day has two
updaters. Each updater allows at most two open version-update pull requests and applies a
five-day release cooldown. These backpressure controls do not delay or count Dependabot
security-update pull requests.

Required status checks and the active `main-standard` ruleset remain authoritative; neither
Dependabot nor Mergify bypasses them. Mergify may automatically queue only the explicitly
allowlisted routine Dependabot groups, one PR at a time. Queue and merge conditions are
identical and explicitly mirror the required contexts declared in `.github/rulesets/main.json`,
which keeps Mergify compatible with the strict up-to-date ruleset using in-place checks.
Repository tests require exact ruleset and queue/merge-condition parity, so Mergify does
not rely on external ruleset-discovery APIs to decide that CI is complete. Human, release,
security, major, and other ungrouped PRs are
not auto-queued by repository policy. They may enter the command-only `maintainer` queue
rule when a user with write access comments `@mergifyio queue`; that rule mirrors the same
required contexts, requires resolved review threads, and has no automatic trigger.

### SonarQube Cloud scope

This project runs **CI-based analysis** via
`.github/workflows/sonarcloud.yml`, which triggers on every push to `main`
and on pull requests. The workflow installs dependencies, runs the full test
suite with coverage, and invokes `SonarSource/sonarqube-scan-action` (pinned
to v8.2.2). The scanner reads `sonar-project.properties` from the repository
root — this is the CI-based configuration file (distinct from
`.sonarcloud.properties`, which is used only by SonarCloud's Automatic
Analysis mode and must not coexist with a CI workflow).
`sonar-project.properties` sets `sonar.tests` to classify `tests/`,
`packages/protocol-schemas/test/`, and `packages/kicad-fixtures/test/` as
test code. This only affects path classification — it does not exclude any
file from analysis, and it does not change rule severities or Quality
Profiles (those require SonarQube Cloud UI/admin access, not a repo file).
SonarCloud Scan is a required status check. Trusted same-repository PRs run the real analysis; Dependabot, fork, and release-metadata-only PRs take an explicit successful no-op path that does not expose `SONAR_TOKEN`. Mergify requires literal `check-success` for this context rather than accepting skipped/neutral conclusions.

## Publish Workflows

All publish workflows enforce strict safety:

- **Trigger**: Only `release` (published) or `workflow_dispatch` with explicit
  inputs.
- **PR context**: Dry-run only (build without push, validate without publish).
- **Environment protection**: publish jobs remain bound to their configured
  GitHub environments (`pypi`, `testpypi`, `npm`, `mcp-registry`, and
  `ghcr` as applicable). The repository-settings audit expects zero required
  reviewers on `npm`, `mcp-registry`, and `ghcr`; adding a reviewer there is
  policy drift unless the publish policy is intentionally changed.
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

## Repository settings drift audit

`.github/workflows/repository-settings-audit.yml` runs daily and on manual dispatch from the
default branch. It mints a short-lived GitHub App token with `Actions: read` and
`Administration: read` permissions; a missing or under-scoped token fails the audit.
The workflow itself has `contents: read` permissions and is not exposed to pull requests.
`scripts/check_github_repository_settings.py` compares live Actions permissions,
selected-action allowlists, default workflow-token permissions, protected publish
environments, and the repository rulesets against the reviewed JSON policy.

GitHub's ruleset API **withholds `bypass_actors` from read-only tokens** (it requires
ruleset write access to disclose them). The scheduled audit therefore warns when this
field is absent and treats it as **unverified**, not as an empty actor list. All other
ruleset fields are compared strictly. When an authorized maintainer runs the same audit
with ruleset write access, a returned `bypass_actors` list is compared strictly as well.
This visibility constraint does not justify granting the scheduled audit write permissions,
and missing bypass visibility must not be reported as verified compliance.

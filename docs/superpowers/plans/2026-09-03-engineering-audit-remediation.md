# Engineering Audit Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the audit's actionable repository and GitHub engineering gaps, then generate real live-model/native-KiCad evidence where available.

**Architecture:** Extend existing policy and release primitives rather than introducing a parallel governance framework. Keep network/live-state checks testable as pure validation functions, and keep protected inference separate from deterministic CI/release checks.

**Tech Stack:** Python 3.13, pytest, GitHub Actions/YAML, GitHub REST via `gh`, npm/pnpm, KiCad CLI/native-live harness.

**Spec:** `docs/superpowers/specs/2026-09-03-engineering-audit-remediation-design.md`

## Global Constraints
- Work only on `remediation/engineering-audit-2026-09`, never directly on `main`.
- Preserve SHA-pinned Actions and least-privilege job permissions.
- New Python behaviour follows RED → GREEN → refactor.
- Never mark live/native evidence passed without satisfying the repository evidence contract.
- Do not remove `NPM_TOKEN` until npm Trusted Publisher registration is externally verified.

---

### Task 1: Live GitHub Actions settings drift sensor
**Files:** create `scripts/check_github_repository_settings.py`; create `tests/unit/test_github_repository_settings.py`; modify `package.json` and policy docs if needed.
- [ ] Write tests for hardened Actions permissions, selected allowlist, workflow-token defaults, and mismatch reporting.
- [ ] Run focused tests and observe failure because the checker does not exist.
- [ ] Implement pure validation plus a `gh api` live adapter.
- [ ] Run focused tests and repository workflow-policy checks.
### Task 2: Release-time live-model enforcement
**Files:** modify `scripts/check_live_model_release_policy.py`, `tests/unit/test_live_model_release_policy.py`, `.github/workflows/release.yml`, `docs/engineering/ci-cd-policy.md`.
- [ ] Add failing tests for a CLI mode that returns non-zero when release readiness is `full`.
- [ ] Implement `--require-ready` without changing classification semantics.
- [ ] Add a release-validation step for release-please PRs and published releases.
- [ ] Update docs so they describe actual pre-release enforcement instead of a nonexistent required PR check.
- [ ] Run focused tests and workflow policy/lint.

### Task 3: MCP Registry bootstrap integrity
**Files:** modify `.github/workflows/publish-mcp-registry.yml`; create/update a workflow contract test.
- [ ] Add a failing test that requires the reviewed v1.7.9 Linux amd64 SHA-256 and `sha256sum --check` before extraction.
- [ ] Pin `ab128162b0616090b47cf245afe0a23f3ef08936fdce19074f5ba0a4469281ac` in workflow env and verify before `tar`.
- [ ] Run focused test and workflow policy/security checks.

### Task 4: Agent routing and catalog-doc drift
**Files:** create root `AGENTS.md`; modify `README.md`, `docs/agents/progressive-disclosure.md`, `docs/agents/toolsets.md`; add doc contract test if appropriate.
- [ ] Add a failing test that rejects hard-coded stale expert catalog counts in agent-facing prose and requires root router links.
- [ ] Replace numeric expert-catalog prose with links to generated profile evidence.
- [ ] Add concise root router to architecture, test, security, tool-contract, and agent docs.
- [ ] Run focused tests, metadata/profile/toolset checks.

### Task 5: Live publish-environment protection
**Live GitHub configuration only.**
- [ ] Preserve existing environment settings and add explicit required reviewer protection to `npm` and `mcp-registry`.
- [ ] Re-query both environments and record exact live state.
- [ ] Do not add reviewer gating to automated `live-model-evals` smoke.
### Task 6: Live-model baseline evidence
**Live workflow plus reviewed artifact.**
- [ ] Dispatch the existing full `Live Model Release Gate` on current `main`.
- [ ] Monitor smoke, repeated benchmark, aggregate, and candidate-baseline jobs.
- [ ] If and only if the gate succeeds, download the candidate baseline artifact and verify its source revision/configuration set.
- [ ] Promote the generated candidate to `evals/live/baselines.yaml`; otherwise leave baseline unapproved and report the real blocker.
- [ ] Run release-policy unit tests after promotion.

### Task 7: Native KiCad behavioural evidence
**Files:** use existing `docs/evidence/task-outcomes` and reference-board tooling; do not invent a new schema.
- [ ] Run development diagnostics and confirm KiCad CLI/native capabilities.
- [ ] Locate the canonical task-outcome/reference-board runner and its denominator requirements.
- [ ] Execute safe representative attempts on repository fixtures/reference boards, including mutation recovery and DRC/manufacturing paths where supported.
- [ ] Store only contract-valid evidence and recompute summary statuses.
- [ ] Leave unmet metrics as `insufficient_evidence` with exact missing denominators.

### Task 8: Final verification
- [ ] Run focused unit suites for all modified contracts.
- [ ] Run `format:check`, `lint`, `typecheck`, metadata/profile/toolset/tool-contract checks, workflow policy/lint/security, and release validation that are available locally.
- [ ] Run the broad unit suite; report any environment-only skipped/blocked Rust/Tauri checks separately.
- [ ] Re-query live Actions settings and publish environments.
- [ ] Review `git diff --check`, `git status`, and the complete diff before any commit/push.
- [ ] Commit logically separated changes on the remediation branch; do not merge to `main` without the repository's protected process.
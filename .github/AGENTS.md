# CI, Security, and Release Automation Instructions

These instructions apply to `.github/**` and supplement the repository root `AGENTS.md`.

## Boundary

Workflow, ruleset, dependency-bot, CODEOWNERS, and release automation changes are policy changes. They can alter branch protection, supply-chain trust, publication identity, evidence, and security posture.

Read first:

- `docs/engineering/ci-cd-policy.md`
- `docs/security/github-actions-policy.md`
- `docs/security/release-integrity.md`
- `docs/development/release-process.md`
- `.github/actions-policy.json`
- `.github/rulesets/main.json`
- `.github/rulesets/release-tags.json`

## Required-check integrity

Required status contexts are repository interfaces.

Preserve the contexts documented in `docs/engineering/ci-cd-policy.md`, including the aggregate `Required PR Gate`, unless the live ruleset is intentionally migrated and verified in the same change.

- Do not path-filter an entire required workflow in a way that leaves branch protection waiting for a context that never reports.
- Preserve the step-level no-op pattern where required checks must report success for non-applicable changes.
- Do not rename a required job casually; reconcile the ruleset, Mergify conditions, policy tests, and documentation together.
- Do not use `continue-on-error`, exclusions, or trigger narrowing to hide a repository-owned failure.

The local pytest coverage threshold remains blocking. Codecov project/patch statuses and test analytics are reporting/telemetry under the current policy; do not accidentally turn external reporting availability into the sole coverage authority.

## Permissions and untrusted input

- Keep workflow-scope permissions read-only by default.
- Add write scopes only at the narrow job that needs them and update `.github/actions-policy.json` in the same change.
- Keep third-party Actions pinned to full commit SHAs.
- Do not expose secrets to untrusted fork code.
- Do not interpolate PR-controlled expressions into shell commands without a safe boundary.
- Preserve separation between untrusted validation and privileged publication.

## Security automation

Do not weaken or silently bypass:

- Gitleaks;
- CodeQL;
- Dependency Review;
- workflow policy/actionlint/zizmor enforcement;
- dependency and filesystem/container vulnerability checks;
- repository-settings drift auditing;
- protected environment expectations.

External scanner or SaaS outages should be distinguished from repository-owned validation failures; do not suppress a real policy failure to make a run green.

## Release and supply-chain automation

Production publication is privileged code. Preserve:

- release/tag/source identity;
- protected environments;
- OIDC/trusted publishing;
- artifact attestations and provenance;
- SBOM and checksum evidence;
- Sigstore/cosign verification where configured;
- Python/npm/container/MCP Registry/protocol-schema channel semantics;
- idempotency and post-publication verification.

Do not publish from a local workstation, repoint immutable release tags, silently replace released assets, or replay a successful publication mutation merely to repeat verification.

Human-only manufacturing controls and live-model release evidence are separate from software package publication; workflow refactors must not collapse those trust boundaries.

## Workflow validation

For `.github` behavior changes run:

```bash
pnpm run workflows:policy
pnpm run workflows:lint
pnpm run workflows:security
```

Run the focused repository tests that lock ruleset/Mergify/required-check/release behavior and use `task ci` only when the change crosses enough boundaries to justify the full local CI equivalent.

A YAML parser passing is not sufficient. Validate permissions, trigger behavior, required contexts, artifact/evidence dependencies, and publication identity.

## Definition of done

A GitHub automation change is complete only when workflow semantics, permissions, pins, required checks, repository policy tests, security controls, release evidence, and live repository settings remain consistent.

# Engineering Audit Remediation Design

## Goal
Close the audit's actionable engineering gaps without weakening the repository's existing deterministic-first architecture, least-privilege workflow model, or progressive-disclosure agent surface.

## Scope
Phase 1 covers GitHub enforcement drift, CI/release policy, supply-chain bootstrap integrity, agent routing/docs drift, and publish-environment protection. Phase 2 produces real live-model and native-KiCad evidence where the existing credentials/runtime support it.

## Design principles
- Keep `main` untouched until review/merge; work in an isolated remediation branch.
- Prefer existing `Required PR Gate` and existing release-policy primitives over adding parallel gate frameworks.
- Separate repository configuration checks from live GitHub-state checks.
- Do not claim behavioural evidence unless a real run satisfies the repository's evidence contract.
- Do not remove a publishing credential until the replacement trust relationship is known to exist.

## GitHub policy
The checked-in `.github/actions-policy.json` remains the source of truth. Live Actions settings are reconciled to it immediately. A live-state checker will compare API responses with the policy and fail closed on mismatches when an admin-capable audit token is supplied.

## Live-model policy
PR CI will deterministically classify release-policy impact and expose that result through the existing `Required PR Gate`. Actual provider calls remain in the protected `live-model-evals` environment. Release readiness must fail when the approved baseline is missing, stale, or contract-mismatched.
## Supply chain
The MCP Registry bootstrap binary is verified against a review-pinned SHA-256 from the upstream v1.7.9 release checksums before extraction. npm publishing is migrated to Trusted Publishing only after the npm-side publisher registration can be verified; until then the existing release path is kept functional and the remaining external action is documented explicitly.

## Agent harness and documentation
Add a short root `AGENTS.md` that routes coding agents to architecture, testing, security, and generated-contract sources instead of duplicating them. Remove hard-coded expert-catalog counts from prose and point readers at generated profile evidence so future catalog growth cannot silently stale the docs.

## Environment protection
Publishing environments that currently have no protection are updated with an explicit human reviewer where that does not break unattended assurance workflows. Live-model smoke remains automatable; manual full-gate promotion remains protected.

## Evidence
Run the existing full live-model gate on current `main`; if it succeeds, promote only its generated candidate baseline. For KiCad behaviour, use the repository's native-live/reference-board contracts and record `insufficient_evidence` for any unmet denominator rather than fabricating success.

## Verification
Every code behaviour change gets a failing test first, then implementation, then focused tests. Final verification includes workflow policy/lint, relevant unit suites, metadata/profile/doc checks, git diff/status review, and live GitHub-state re-query. Rust/Tauri verification is reported separately if the local toolchain remains unavailable.
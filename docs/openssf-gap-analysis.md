# OpenSSF gap analysis

This file records gaps that prevent a stronger OpenSSF Gold / foundation-grade claim. These items are intentionally not marked as passed without evidence.

## Current target

- Target: **Professional OSS / Mature OSS**.
- OpenSSF target: **maintain Passing/Silver evidence and improve Scorecard readiness**.
- Gold status: **not claimed**.

## Gold / foundation-grade blockers

| Gap | Classification | Why it matters | Recommended action |
| --- | --- | --- | --- |
| Single active maintainer | Partial | Bus factor is 1. Gold/foundation-grade needs continuity beyond one person. | Recruit and onboard at least one trusted co-maintainer. |
| No independent human PR review evidence | Missing | Recent sampled merged PRs had zero recorded reviews. Bot checks do not replace human review. | Require one human approval once there is a second maintainer. |
| Branch protection not confirmed by classic API | Needs human confirmation | Policy-as-code exists, but GitHub settings must enforce it. | Enable/verify repository ruleset and required checks in GitHub UI. |
| Private reporting setting | Needs human confirmation | `SECURITY.md` links private reports, but setting is external to git. | Enable private reporting and confirm with owner access. |
| Secret scanning / push protection | Needs human confirmation | Requires GitHub settings/plan visibility. | Enable if available and document status. |
| SLSA level not formally defined | Partial | Attestations exist, but formal SLSA claim requires scoped evidence. | Define per-artifact SLSA target before claiming. |
| REUSE/SPDX lint not enforced | Partial | Root license exists, but file-level license metadata has not been fully assessed. | Run REUSE audit in report-only mode, then decide enforcement. |
| Dependency license report | Partial | Security audit exists; license inventory should be explicit for legal maturity. | Add license-report generation to release evidence if needed. |

## Non-blocking improvements

- Add non-blocking OSV Scanner scheduled workflow.
- Add non-blocking hadolint/Trivy/grype container checks with tuned allowlist.
- Add issue response metrics generated from GitHub API.
- Add contributor recognition only if community participation grows.
- Add a maintainer rotation and release shadowing process after a co-maintainer joins.

## Do not overclaim

Do not advertise Gold, foundation-grade, or CNCF-graduated-style status until multiple active maintainers, independent review, settings enforcement, release and security continuity, and consistent Scorecard/BadgeApp evidence exist.

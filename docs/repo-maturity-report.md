# Repository maturity report

Assessment date: 2026-07-02
Repository: `oaslananka/kicad-mcp-pro`
Mode: audit + implementation PR

## Executive summary

`kicad-mcp` already has many strong professional open-source signals: README, MIT license, contribution guide, code of conduct, security policy, support policy, release automation, CI, CodeQL, Gitleaks, Scorecard, fuzzing, package metadata, OpenSSF Silver evidence, generated tool references, and documented governance.

The current maturity level is **Professional OSS / Mature OSS**. This report does **not** claim Gold or foundation-grade status because several conditions need human confirmation or are not yet true: single active maintainer, no evidence of independent human PR review in sampled recent PRs, classic branch protection is not used because an active GitHub ruleset protects `main`, and only team-growth controls remain out of scope for a solo maintainer.

## Current maturity level

**Professional OSS / Mature OSS — Passed/Partial.**

Evidence includes public repository, MIT license, active CI, release automation, strong security workflows, OpenSSF Silver evidence, documented governance, issue templates, PR template, support policy, and generated reference docs.

## Target maturity level

Primary target: **Professional OSS / Mature OSS**.

Gold / foundation-grade is not a current target for this solo-maintainer repository. If the project later grows into a multi-maintainer project, the optional Gold gap list can be revisited.

## GitHub Community Standards status

| Criterion | Status | Evidence / notes |
| --- | --- | --- |
| README | Passed | `README.md` describes project scope, identity, install options, and docs. |
| LICENSE | Passed | `LICENSE` is present; GitHub API reports MIT. |
| CONTRIBUTING | Passed | `CONTRIBUTING.md` documents DCO, setup, quality gates, and PR process. |
| CODE_OF_CONDUCT | Passed | `CODE_OF_CONDUCT.md` is present. |
| SECURITY | Passed | `SECURITY.md` documents private reporting and response targets. |
| SUPPORT | Passed | `SUPPORT.md` documents issue, discussion, security, and conduct channels. |
| Issue templates | Passed | Bug, feature, documentation templates and config exist. |
| Pull request template | Passed | `.github/PULL_REQUEST_TEMPLATE.md` exists. |
| Discussions | Passed | GitHub repository settings report Discussions enabled. |

## OpenSSF Best Practices status

| Area | Status | Evidence / notes |
| --- | --- | --- |
| Passing readiness | Passed | `docs/openssf-best-practices.md`, `docs/openssf-evidence.md`. |
| Silver readiness | Passed / Partial | Existing Silver evidence; this PR adds consolidated evidence and gaps. |
| Gold feasibility | Not applicable | Gold is intentionally not targeted for the current solo-maintainer model. |
| `.bestpractices.json` | Passed | Added in this PR. |
| BadgeApp proposal links | Passed | `docs/openssf-proposal-links.md`. |
| Evidence file | Passed | `docs/openssf-evidence.md`. |

## Scorecard readiness

| Check area | Status | Evidence / notes |
| --- | --- | --- |
| Branch protection / rulesets | Passed | GitHub ruleset `main` is active for branch protection; classic branch protection is not used. |
| Code review | Partial / Not applicable for solo maintainer | PR template and checks exist. Independent human review is optional until another trusted maintainer exists. |
| Maintained | Passed | Recent pushes and PR activity. |
| Security policy | Passed | `SECURITY.md`. |
| License | Passed | MIT license. |
| CI tests | Passed | `ci.yml` and multiple quality gates. |
| Dependency update tool | Passed | Renovate is configured with vulnerability alerts, lockfile maintenance, and package update policy. |
| Pinned dependencies | Passed / Partial | Actions are mostly SHA-pinned; workflow-security checks continue enforcement. |
| Token permissions | Passed / Partial | Workflows default to `contents: read`; release jobs escalate intentionally. |
| Dangerous workflows | Passed / Partial | Workflow security checks exist; keep auditing release workflows. |
| SAST | Passed | CodeQL, Bandit, Ruff, mypy. |
| Fuzzing | Passed | Fuzz workflow and Atheris target exist. |

## Documentation maturity

| Diataxis quadrant | Status | Evidence / notes |
| --- | --- | --- |
| Tutorial | Partial -> Passed | `docs/tutorials/getting-started.md` added. |
| How-to guides | Partial -> Passed | `docs/how-to/index.md` added as a task map. |
| Reference | Passed | Generated tool catalog, MCP docs, runtime matrices; `docs/reference/index.md` added. |
| Explanation | Passed / Partial | Architecture docs and ADRs exist; `docs/explanation/architecture.md` added. |
| Discoverability | Partial -> Passed | README, docs index, and MkDocs nav link maturity/process docs. |

## Release maturity

| Criterion | Status | Evidence / notes |
| --- | --- | --- |
| Semantic Versioning | Passed | `CHANGELOG.md` states SemVer. |
| CHANGELOG | Passed | Release-please/Keep a Changelog style. |
| GitHub Releases | Passed | Release workflows and release validation exist; environment approvals remain repository-owner controlled. |
| Release notes | Passed | `CHANGELOG.md`, release-please. |
| Release workflow | Passed | Existing release-please/publish workflows; release validation workflow added. |
| Checksums | Passed | Release evidence generates checksums. |
| Provenance / attestation | Passed / Partial | Attestation/provenance present where supported. |

## Quality maturity

| Criterion | Status | Evidence / notes |
| --- | --- | --- |
| CI workflow | Passed | CI on PRs and `main`. |
| Lint | Passed | Ruff. |
| Typecheck | Passed | mypy and TypeScript checks. |
| Unit tests | Passed | Unit suite exists and was run in chunks during audit. |
| Integration tests | Passed | Integration/E2E suites exist and were run in chunks during audit. |
| Coverage threshold | Passed | `pyproject.toml` coverage fail-under is 83. |
| Test policy | Passed | `docs/development/testing-policy.md`. |
| Coding standards | Passed | `docs/development/coding-standards.md`. |
| Dependency update policy | Passed | `docs/development/dependency-management.md`; dependency review workflow added. |

## Governance maturity

| Criterion | Status | Evidence / notes |
| --- | --- | --- |
| GOVERNANCE | Passed | `GOVERNANCE.md`. |
| MAINTAINERS | Passed | `MAINTAINERS.md`. |
| ROADMAP | Passed | `ROADMAP.md`. |
| CODEOWNERS | Passed | `.github/CODEOWNERS`. |
| Support policy | Passed | `SUPPORT.md`. |
| Deprecation policy | Passed / Partial | Roadmap, runtime policy, release docs. |
| Backward compatibility policy | Passed / Partial | API stability docs, tool-contract checks, compatibility matrix. |
| Sustainable governance | Passed for solo maintainer / Partial for multi-maintainer | Solo-maintainer governance is documented; multi-maintainer succession remains optional future work. |

## Community maturity

| Criterion | Status | Evidence / notes |
| --- | --- | --- |
| Time to first response | Needs human confirmation | Requires periodic GitHub issue analytics. |
| Issue resolution process | Passed | Issue templates and support policy. |
| PR review process | Partial | PR template exists; independent review not evidenced. |
| Contributor activity | Partial | Recent PRs active, but sampled PRs authored by same maintainer. |
| Release frequency | Passed | Frequent releases and release PRs. |
| Bus factor / elephant factor | Partial | Single maintainer documented. |
| Documentation discoverability | Passed | Docs site and new maturity map. |

## License/legal maturity

| Criterion | Status | Evidence / notes |
| --- | --- | --- |
| LICENSE | Passed | MIT. |
| SPDX identifiers | Partial | Package metadata declares license; file-level SPDX should be measured. |
| REUSE readiness | Partial | Add REUSE lint only after a repository-wide license-header policy is agreed. |
| License location | Passed | Root `LICENSE`. |
| Third-party dependency license awareness | Partial | Dependency audit exists; add license inventory if consumers require it. |
| NOTICE file | Not applicable / Needs human confirmation | No current evidence that NOTICE is required. |

## Security/supply-chain maturity

| Criterion | Status | Evidence / notes |
| --- | --- | --- |
| SECURITY | Passed | `SECURITY.md`. |
| Private vulnerability reporting | Passed | GitHub private vulnerability reporting was enabled during this hardening pass. |
| CodeQL | Passed | `.github/workflows/codeql.yml`. |
| Gitleaks | Passed | `.github/workflows/gitleaks.yml`. |
| Dependency review | Partial -> Passed | `.github/workflows/dependency-review.yml` added. |
| Dependabot/Renovate | Passed | Renovate configuration includes vulnerability alerts and lockfile maintenance; Dependabot security updates remain intentionally disabled to avoid duplicate PRs. |
| OSV Scanner | Missing / optional | pip-audit exists; OSV can be future non-blocking scheduled check. |
| SBOM | Passed / Partial | Release evidence generates SBOMs where supported. |
| SLSA/provenance | Partial | Formal SLSA level is not claimed. |
| Minimal Actions permissions | Passed / Partial | Most workflows default to least privilege. |

## Missing files

Before this PR: `.bestpractices.json`, `docs/repo-maturity-report.md`, `docs/openssf-evidence.md`, `docs/openssf-gap-analysis.md`, `docs/openssf-proposal-links.md`, Diataxis entry files, `docs/development/commit-conventions.md`, and `docs/development/release-process.md` were missing.

## Missing workflows

Before this PR: `.github/workflows/dependency-review.yml` and `.github/workflows/release.yml` release validation were missing.

## Risky changes not applied

- Enforcing required PR reviews or CODEOWNERS review in GitHub settings.
- Enabling branch protection/rulesets directly in repository settings.
- Requiring DCO bot or CLA checks.
- Adding REUSE lint as a required CI gate before a repository-wide SPDX/header pass.
- Adding OSV Scanner, Trivy, Grype, or hadolint as blocking gates without tuning.
- Changing release/publish permissions or environments beyond validation.
- Claiming OpenSSF Gold or foundation-grade status.

## Recommended issues

1. Enable and verify main branch ruleset enforcement.
2. Introduce human PR review policy once a second trusted maintainer exists.
3. Recruit/onboard a second maintainer.
4. Confirm private vulnerability reporting and secret scanning settings.
5. Add REUSE/SPDX readiness pass.
6. Add dependency license report if package consumers require it.
7. Evaluate OSV Scanner and container linting as non-blocking scheduled checks.
8. Define formal SLSA target for each artifact class before making SLSA claims.

## Next actions

1. Merge this PR after CI passes.
2. Apply the manual GitHub settings listed in the PR description.
3. Update OpenSSF BadgeApp evidence with links from `docs/openssf-proposal-links.md`.
4. Open the recommended issues above and label them `repo-maturity`.
5. Re-run Scorecard after branch/ruleset settings are confirmed.
6. Revisit Gold readiness only if the project intentionally moves beyond a solo-maintainer model.

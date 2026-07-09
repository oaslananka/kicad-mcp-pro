# OpenSSF Silver Evidence

This page maps OpenSSF Silver criteria to repository evidence. It should be updated before completing or resubmitting the Silver form.

## Status

Silver has been achieved for OpenSSF Best Practices project `13377`. Baseline Level 1 is a separate OSPS series and should be handled in a separate hardening pass.

## Evidence map

| Criterion area | Proposed status | Evidence |
| --- | --- | --- |
| Achieve Passing | Met | OpenSSF project `13377` has achieved the Silver badge, which includes Passing as a prerequisite |
| Contribution requirements | Met | [`CONTRIBUTING.md`](https://github.com/oaslananka/kicad-mcp-pro/blob/main/CONTRIBUTING.md), PR template, coding standards |
| DCO / contribution authorization | Met | [`CONTRIBUTING.md`](https://github.com/oaslananka/kicad-mcp-pro/blob/main/CONTRIBUTING.md) Developer Certificate of Origin section |
| Governance | Met | [`GOVERNANCE.md`](https://github.com/oaslananka/kicad-mcp-pro/blob/main/GOVERNANCE.md) |
| Code of conduct | Met | [`CODE_OF_CONDUCT.md`](https://github.com/oaslananka/kicad-mcp-pro/blob/main/CODE_OF_CONDUCT.md) |
| Roles and responsibilities | Met | [`GOVERNANCE.md`](https://github.com/oaslananka/kicad-mcp-pro/blob/main/GOVERNANCE.md), [`MAINTAINERS.md`](https://github.com/oaslananka/kicad-mcp-pro/blob/main/MAINTAINERS.md) |
| Continuity | Met | [`GOVERNANCE.md`](https://github.com/oaslananka/kicad-mcp-pro/blob/main/GOVERNANCE.md) succession and release authority sections |
| Bus factor | Unmet with justification | Single-maintainer status is documented in [`GOVERNANCE.md`](https://github.com/oaslananka/kicad-mcp-pro/blob/main/GOVERNANCE.md) and [`docs/security/scorecard-exceptions.md`](security/scorecard-exceptions.md) |
| Roadmap | Met | [`docs/development/roadmap-2026.md`](development/roadmap-2026.md) |
| Architecture | Met | [`docs/development/architecture.md`](development/architecture.md), ADRs |
| Security requirements | Met | [`docs/security/requirements.md`](security/requirements.md) |
| Quick start | Met | [`README.md`](https://github.com/oaslananka/kicad-mcp-pro/blob/main/README.md), [`docs/installation.md`](installation.md), agent install docs |
| Documentation currency | Met | Docs build, generated tool references, and release checklist |
| Achievements linked | Met | README badges and [`docs/openssf-best-practices.md`](openssf-best-practices.md) |
| Accessibility | Met / partial | [`docs/accessibility.md`](accessibility.md) documents the current policy and limitations |
| Internationalization | Met / partial | [`docs/internationalization.md`](internationalization.md) documents English-first policy and localization readiness |
| Password storage for project sites | N/A | Project does not operate custom project-site authentication or password storage |
| Previous-version maintenance | Met | [`docs/maintenance-policy.md`](maintenance-policy.md), release notes, changelog |
| Issue tracker | Met | GitHub Issues and issue templates |
| Vulnerability credit | Met | [`SECURITY.md`](https://github.com/oaslananka/kicad-mcp-pro/blob/main/SECURITY.md) |
| Vulnerability response process | Met | [`SECURITY.md`](https://github.com/oaslananka/kicad-mcp-pro/blob/main/SECURITY.md) response targets and disclosure process |
| Coding standards | Met | [`docs/development/coding-standards.md`](development/coding-standards.md) |
| Style enforcement | Met | Ruff, mypy, TypeScript, metadata checks, CI |
| Build variables and build hardening | N/A / Met where applicable | Python/TypeScript project; native compiler variables mostly N/A, Docker and workflow hardening documented |
| Installation system | Met | [`docs/installation.md`](installation.md), [`docs/development/installation-policy.md`](development/installation-policy.md) |
| External dependencies | Met | [`docs/development/dependency-management.md`](development/dependency-management.md), lockfiles, dependency audit |
| Automated integration testing | Met | GitHub Actions CI on pull requests and `main` |
| Regression testing | Met | [`docs/development/testing-policy.md`](development/testing-policy.md) |
| Coverage 80% | Met | Python coverage is configured with `tool.coverage.report.fail_under = 83` in [`pyproject.toml`](https://github.com/oaslananka/kicad-mcp-pro/blob/main/pyproject.toml), and the testing policy documents the 80% Silver target. |
| Mandatory new functionality tests | Met | [`docs/development/testing-policy.md`](development/testing-policy.md), [`CONTRIBUTING.md`](https://github.com/oaslananka/kicad-mcp-pro/blob/main/CONTRIBUTING.md) |
| Strict warnings | Met | Ruff, mypy, TypeScript, CodeQL, security jobs, workflow checks |
| Secure design implementation | Met | [`docs/security/requirements.md`](security/requirements.md), [`docs/security/assurance-case.md`](security/assurance-case.md) |
| Crypto requirements | N/A where custom crypto is absent; Met for release verification | [`docs/security/release-signing.md`](security/release-signing.md), [`docs/security/release-integrity.md`](security/release-integrity.md) |
| Signed releases | Met | Sigstore/GitHub attestations, npm provenance, cosign-signed container images, checksums, SBOMs |
| Input validation | Met | [`docs/security/input-validation.md`](security/input-validation.md) |
| Hardening | Met / partial | Workflow hardening, pinned Actions, digest-pinned containers, minimal permissions, Scorecard exceptions |
| Assurance case | Met | [`docs/security/assurance-case.md`](security/assurance-case.md) |
| SAST common vulnerabilities | Met | CodeQL, Bandit, Ruff, mypy, Gitleaks, dependency audit, workflow-security checks |
| Dynamic unsafe-language analysis | N/A | Project is primarily Python/TypeScript and does not ship C/C++ memory-unsafe code |

## Submission guidance

Use the Silver edit URL:

```text
https://www.bestpractices.dev/en/projects/13377/silver/edit
```

Silver claims have been submitted and accepted for project `13377`. Keep this evidence page current before any Silver resubmission or Gold preparation pass.

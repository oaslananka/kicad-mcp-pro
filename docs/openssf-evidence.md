# OpenSSF evidence

This file consolidates evidence for OpenSSF Best Practices and Scorecard-style repository maturity checks. It does not claim Gold readiness.

## Project identity

| Field | Evidence |
| --- | --- |
| Repository | <https://github.com/oaslananka/kicad-mcp> |
| Documentation | <https://oaslananka.github.io/kicad-mcp/> |
| License | `LICENSE` (MIT) |
| Package metadata | `pyproject.toml`, `package.json`, `server.json` |
| OpenSSF BadgeApp project | <https://www.bestpractices.dev/projects/13377> |

## Passing / Silver evidence map

| OpenSSF area | Status | Evidence |
| --- | --- | --- |
| Basic project description | Passed | `README.md`, docs site, package metadata. |
| How to obtain/use | Passed | `README.md`, `docs/installation.md`, `docs/tutorials/getting-started.md`. |
| Feedback / contribution process | Passed | `SUPPORT.md`, issue templates, `CONTRIBUTING.md`. |
| License | Passed | `LICENSE`, package metadata. |
| Documentation and reference | Passed | MkDocs site, generated tools reference, MCP docs. |
| Versioned source repository | Passed | Public GitHub repo with release tags. |
| Release notes | Passed | `CHANGELOG.md`, release-please workflow, publish workflows. |
| Bug reporting | Passed | GitHub issue templates and support policy. |
| Private security reports | Passed / Needs setting confirmation | `SECURITY.md`; confirm private reporting in GitHub UI. |
| Automated build/test | Passed | `ci.yml`, `package.json` scripts, `Taskfile.yml`. |
| New functionality tests | Passed | PR template and testing policy require tests or documented justification. |
| Static analysis | Passed | Ruff, mypy, CodeQL, Bandit, workflow-security checks. |
| Fuzzing / dynamic analysis | Passed / Partial | Fuzz workflow exists; expand as parsers grow. |
| Governance and roles | Passed / Partial | Governance docs exist; single-maintainer model blocks Gold. |
| Roadmap | Passed | `ROADMAP.md` and docs roadmap. |
| Architecture | Passed | `ARCHITECTURE.md`, `docs/development/architecture.md`, ADRs. |
| Security requirements | Passed | `docs/security/requirements.md`, threat model, assurance case. |
| Coverage threshold | Passed | `pyproject.toml` coverage fail-under is 83. |

## Scorecard evidence map

| Scorecard check | Status | Evidence / note |
| --- | --- | --- |
| Branch-Protection | Partial / Needs human confirmation | `.github/rulesets/main.json`; classic API returned branch not protected. |
| Code-Review | Partial | PR template exists; recent sampled PRs had no recorded reviews. |
| Maintained | Passed | Recent pushes and active PR history. |
| Security-Policy | Passed | `SECURITY.md`. |
| License | Passed | MIT. |
| CI-Tests | Passed | `ci.yml` and supporting workflows. |
| Dependency-Update-Tool | Passed / Partial | Renovate is documented; Dependabot config intentionally empty. |
| Pinned-Dependencies | Passed / Partial | Actions are pinned to SHAs; continue workflow-security checks. |
| Token-Permissions | Passed / Partial | Minimal default permissions; release jobs escalate intentionally. |
| Dangerous-Workflow | Passed / Partial | Workflow security checks and no `pull_request_target` evidence in audit. |
| SAST | Passed | CodeQL, Bandit, Ruff, mypy. |
| Fuzzing | Passed | Fuzz workflow and target exist. |

## Evidence maintenance

Update this file when workflow names, release process, OpenSSF badge status, governance, GitHub settings, or published artifact classes change.

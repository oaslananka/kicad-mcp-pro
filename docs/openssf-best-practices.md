# OpenSSF Best Practices Evidence

This page maps the repository evidence used for the OpenSSF Best Practices checklist. Keep it current whenever project governance, security, release, testing, or reporting workflows change.

## Current target

The project has achieved the Silver badge and maintains a Silver evidence map. Silver evidence is tracked in [`openssf-silver-evidence.md`](openssf-silver-evidence.md). Baseline Level 1 is a separate OSPS series and is intentionally handled in a separate pass.

## Evidence map

| Area | Status | Evidence |
| --- | --- | --- |
| Project name and description | Met | [`README.md`](https://github.com/oaslananka/kicad-mcp-pro/blob/main/README.md), [`pyproject.toml`](https://github.com/oaslananka/kicad-mcp-pro/blob/main/pyproject.toml), [`server.json`](https://github.com/oaslananka/kicad-mcp-pro/blob/main/server.json) |
| Public source repository | Met | Canonical repository: <https://github.com/oaslananka/kicad-mcp-pro> |
| FLOSS license | Met | [`LICENSE`](https://github.com/oaslananka/kicad-mcp-pro/blob/main/LICENSE), package metadata in [`pyproject.toml`](https://github.com/oaslananka/kicad-mcp-pro/blob/main/pyproject.toml) |
| Basic project website | Met | Documentation site: <https://oaslananka.github.io/kicad-mcp-pro/> |
| Contribution process | Met | [`CONTRIBUTING.md`](https://github.com/oaslananka/kicad-mcp-pro/blob/main/CONTRIBUTING.md), pull request template, issue templates |
| Code of conduct | Met | [`CODE_OF_CONDUCT.md`](https://github.com/oaslananka/kicad-mcp-pro/blob/main/CODE_OF_CONDUCT.md) |
| Support / reporting channels | Met | [`SUPPORT.md`](https://github.com/oaslananka/kicad-mcp-pro/blob/main/SUPPORT.md), GitHub Issues, GitHub Discussions, private GitHub Security Advisories |
| Vulnerability reporting | Met | [`SECURITY.md`](https://github.com/oaslananka/kicad-mcp-pro/blob/main/SECURITY.md), GitHub private vulnerability report URL |
| Governance and maintainer continuity | Met | [`GOVERNANCE.md`](https://github.com/oaslananka/kicad-mcp-pro/blob/main/GOVERNANCE.md), [`MAINTAINERS.md`](https://github.com/oaslananka/kicad-mcp-pro/blob/main/MAINTAINERS.md) |
| Documentation | Met | [`docs/index.md`](index.md), [`docs/tools-reference.generated.md`](tools-reference.generated.md), workflow docs |
| Automated tests | Met | [`tests/`](https://github.com/oaslananka/kicad-mcp-pro/tree/main/tests), [`package.json`](https://github.com/oaslananka/kicad-mcp-pro/blob/main/package.json), [`.github/workflows/ci.yml`](https://github.com/oaslananka/kicad-mcp-pro/blob/main/.github/workflows/ci.yml) |
| Static analysis | Met | Ruff, mypy, CodeQL, Bandit, workflow-security checks in [`package.json`](https://github.com/oaslananka/kicad-mcp-pro/blob/main/package.json) and GitHub workflows |
| Fuzzing | Met | Atheris fuzz target in [`fuzz/fuzz_sexpr.py`](https://github.com/oaslananka/kicad-mcp-pro/blob/main/fuzz/fuzz_sexpr.py) and scheduled fuzz workflow in [`.github/workflows/fuzz.yml`](https://github.com/oaslananka/kicad-mcp-pro/blob/main/.github/workflows/fuzz.yml) |
| Dependency and container scanning | Met | [`scripts/audit_dependencies.py`](https://github.com/oaslananka/kicad-mcp-pro/blob/main/scripts/audit_dependencies.py), Trivy workflow steps, Gitleaks workflow |
| Release process | Met | [`docs/release-process.md`](release-process.md), release-please workflow, publish workflows |
| Release integrity | Met | [`docs/security/release-integrity.md`](security/release-integrity.md), SBOM/checksum/attestation release steps |
| Branch protection policy as code | Met | [`.github/rulesets/main.json`](https://github.com/oaslananka/kicad-mcp-pro/blob/main/.github/rulesets/main.json), [`docs/branch-protection.md`](branch-protection.md), Scorecard exceptions in [`docs/security/scorecard-exceptions.md`](security/scorecard-exceptions.md) |
| Branch protection active in GitHub | Met | Repository ruleset `main` is active on `refs/heads/main`; verify with `gh api /repos/oaslananka/kicad-mcp-pro/rulesets` |
| OpenSSF Silver evidence | Met | [`docs/openssf-silver-evidence.md`](openssf-silver-evidence.md), Silver badge for project `13377` |
| HTTPS project URLs | Met | GitHub repository, documentation site, package URLs, and badges use HTTPS |
| English documentation and reports | Met | Repository documentation, issue templates, security policy, and support documents are written in English |

## Form-filling guidance

Use stable public URLs when completing the OpenSSF Best Practices form. Prefer repository URLs that point to `main` for living policy documents and release-tag URLs for release-specific evidence.

Recommended evidence URLs:

- `https://github.com/oaslananka/kicad-mcp-pro/blob/main/README.md`
- `https://github.com/oaslananka/kicad-mcp-pro/blob/main/LICENSE`
- `https://github.com/oaslananka/kicad-mcp-pro/blob/main/CONTRIBUTING.md`
- `https://github.com/oaslananka/kicad-mcp-pro/blob/main/CODE_OF_CONDUCT.md`
- `https://github.com/oaslananka/kicad-mcp-pro/blob/main/SECURITY.md`
- `https://github.com/oaslananka/kicad-mcp-pro/blob/main/SUPPORT.md`
- `https://github.com/oaslananka/kicad-mcp-pro/blob/main/GOVERNANCE.md`
- `https://github.com/oaslananka/kicad-mcp-pro/blob/main/MAINTAINERS.md`
- `https://github.com/oaslananka/kicad-mcp-pro/blob/main/docs/release-process.md`
- `https://github.com/oaslananka/kicad-mcp-pro/blob/main/docs/security/release-security.md`
- `https://github.com/oaslananka/kicad-mcp-pro/blob/main/docs/workflow-security.md`
- `https://github.com/oaslananka/kicad-mcp-pro/actions/workflows/ci.yml`
- `https://github.com/oaslananka/kicad-mcp-pro/actions/workflows/codeql.yml`
- `https://github.com/oaslananka/kicad-mcp-pro/actions/workflows/fuzz.yml`
- `https://github.com/oaslananka/kicad-mcp-pro/actions/workflows/gitleaks.yml`
- `https://github.com/oaslananka/kicad-mcp-pro/actions/workflows/scorecard.yml`

## Maintenance checklist

Before a release or OpenSSF resubmission:

1. Run `corepack pnpm run check:ci` or the documented full CI equivalent.
2. Confirm `gh api /repos/oaslananka/kicad-mcp-pro/rulesets` shows an active `main` ruleset.
3. Confirm private vulnerability reporting is enabled in repository settings.
4. Confirm issue templates and discussion links render in GitHub.
5. Confirm release artifacts include checksums, SBOMs, and attestations when the workflow supports them.
6. Update this evidence page when policies, workflow names, package names, or release gates change.

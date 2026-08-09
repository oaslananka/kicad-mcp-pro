# Maintenance Policy

## Local Gates

Use these commands before pushing:

```bash
task install
task pre-push
task ci
```

`task pre-push` runs only checks selected by the files being pushed: scoped Ruff
and mypy, matching unit tests, architecture/tool-contract checks, and conditional
workflow, web, Cargo, metadata, or compatibility validation. `task ci` remains the
full local parity command and includes the repository-wide suite with the 83%
coverage threshold, security checks, docs/package builds, and release validation.

`task security:local` is stricter about workstation tools. It requires
Gitleaks, actionlint, and zizmor, and runs OSV Scanner and Trivy when installed.
Missing required binaries fail with install guidance instead of silently
skipping the scan.

## Dependency Updates

Dependabot is the single automated source for security updates and regular
dependency version PRs using `.github/dependabot.yml`. Renovate is intentionally
not configured, which prevents duplicate bot ownership.

All dependency PRs remain subject to the protected `main` ruleset and required CI.
No bot-side automerge bypass is configured. Runtime dependencies, major updates, and
core KiCad/MCP/Pydantic/Typer ecosystem updates require maintainer review.

## Security Scans

Required gates are Ruff, mypy, pytest with coverage, Bandit, the pip-audit backed
dependency audit, Gitleaks in CI, actionlint, and zizmor workflow checks. The
dependency audit may only acknowledge exact package, version, and advisory
combinations that have an upstream no-fix or metadata mismatch, and each
acknowledgement must be recorded in `scripts/audit_dependencies.py` with
authoritative source URLs.

OSV Scanner, Trivy filesystem scans, Scorecard, CodeQL, Hadolint, and
authenticated external supply-chain scans are recommended scheduled or
release-time checks.

## Release Ownership

`release-please` is the changelog and release PR source of truth. Registry
publishing is restricted to protected release workflows after tests, security
checks, build, SBOM, checksums, and artifact attestation complete.

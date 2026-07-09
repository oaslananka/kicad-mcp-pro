# Repository Autonomy

This repository is configured for a single canonical GitHub repository.

## Ownership

- `oaslananka/kicad-mcp-pro` is the canonical source-of-truth and release authority.
- Source changes, issues, releases, package publishing, and documentation
  deployment all happen from that repository.

## CI/CD Authority

Automation runs on `oaslananka/kicad-mcp-pro`:

- CI matrix
- Security scanning
- CodeQL
- Scorecard
- release automation
- documentation deploy
- image and Docker checks
- package-manager publishing jobs

## Secrets

Repository and GitHub Actions secrets are the source of truth for
workflows that need sensitive values. All secrets are managed through
GitHub's encrypted secrets and environments.

## Automation Boundaries

Automation does not publish releases without an explicit manual input, a
release tag trigger configured in the canonical repository, and the protected
`release` environment approval where required.

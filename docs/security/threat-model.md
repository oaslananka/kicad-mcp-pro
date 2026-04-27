# Threat Model

KiCad MCP Pro runs local automation against KiCad projects. The main risks are filesystem access, untrusted MCP clients, supply-chain compromise, and release artifact integrity.

## Trust Boundaries

- The active KiCad project directory is trusted input/output scope.
- MCP clients are not automatically trusted; use the smallest practical profile.
- HTTP transport should be local-only unless protected by bearer token and strict CORS.
- Release artifacts must be built by GitHub Actions and accompanied by SBOM, signatures, and attestations.

## Primary Risks

- A client asks the server to read or write unexpected paths.
- A leaked auth token allows local HTTP tool access.
- A dependency or GitHub Action introduces malicious behavior.
- A release artifact cannot be traced back to source and workflow.

## Controls

- Project path resolution keeps normal writes inside the active project.
- Optional bearer-token auth protects HTTP transport.
- Dependabot, CodeQL, Gitleaks, Scorecard, Trivy, Hadolint, Bandit, pip-audit, and Safety cover the main automated scan layers.
- SBOM, Sigstore signing, checksums, and GitHub artifact attestations accompany release artifacts.

## Reporting

Report vulnerabilities privately through GitHub Security Advisories.

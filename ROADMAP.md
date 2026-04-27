# Roadmap

KiCad MCP Pro follows a monthly minor release cadence and keeps roadmap items visible enough for users to plan around them. Dates are targets, not promises.

## 3.1

- Harden GitHub supply-chain automation: Dependabot, CodeQL, Gitleaks, Scorecard, SBOM, Sigstore, and artifact attestations.
- Expand cross-platform CI coverage for Windows and macOS unit smoke tests.
- Publish a compact README and move long-form setup material into the docs site.

## 3.2

- Add deeper property-based tests for SI, PI, thermal, and project discovery helpers.
- Establish mutation-testing baselines for utility and routing-critical code.
- Improve docs for troubleshooting, API stability, and benchmark fixture contribution.

## 4.0

- Remove APIs that completed the documented deprecation window.
- Revisit profile names and tool grouping only through an RFC.
- Promote KiCad 10 workflows as the primary tested path while preserving clear KiCad 9 compatibility notes where feasible.

## Ownership

The current maintainer owner is `@oaslananka`. Larger API or workflow changes should use the RFC process described in `GOVERNANCE.md`.

# ADR-0001: Repository Topology

**Status:** Accepted, revised
**Date:** 2026-05-15
**Deciders:** @oaslananka

## Context

The project now uses one canonical GitHub repository:

- `oaslananka/kicad-mcp-pro` - canonical source of truth and release authority.

The former split-repository topology has been retired. CI/CD, release, registry,
package-manager, and signing authority now live in the canonical repository.

## Decision

Maintain a single canonical repository at `oaslananka/kicad-mcp-pro`. It
contains all source changes and runs CI, security scanning, release automation,
docs deploy, publishing workflows, SBOM generation, Sigstore signing, and
artifact attestations.

Normal contributors open PRs against `oaslananka/kicad-mcp-pro`.

## Consequences

- Contributors have one public source of truth for code review and automation.
- Public health indicators must point at the canonical repository workflows.
- The `docs/autonomy.md` document must accurately describe this boundary.
- Any future maintainer must have access to `oaslananka/kicad-mcp-pro`.

## Verification

A new contributor can determine the topology from this ADR, `docs/autonomy.md`, and `docs/deployment/repository-topology.md` within 5 minutes.

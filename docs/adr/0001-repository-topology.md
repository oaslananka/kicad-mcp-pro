# ADR-0001: Repository Topology

**Status:** Accepted
**Date:** 2026-05-04
**Deciders:** @oaslananka

## Context

The project uses two repos:

- `oaslananka/kicad-mcp-pro` - canonical, public, source of truth for code and releases.
- `oaslananka-lab/kicad-mcp-pro` - CI/CD execution mirror; automation may run here.

This dual-owner model was adopted to separate commit authority from CI execution authority.

## Decision

Maintain the dual-repo topology. The canonical repo contains all source code. The lab mirror pulls from canonical on a schedule and can run CI, security scanning, release automation, docs deploy, and publishing workflows when those jobs need separated automation authority.

Normal contributors open PRs against canonical. The lab mirror is an automation concern only.

## Consequences

- Contributors need to understand which repository owns code review and which repository is executing a given automation job.
- Public health indicators must make their repository target clear and must not mix canonical and lab-mirror signals without explanation.
- The `docs/autonomy.md` document must accurately describe this boundary.
- Any future maintainer must have access to both repos.

## Verification

A new contributor can determine the topology from this ADR, `docs/autonomy.md`, and `docs/deployment/repository-topology.md` within 5 minutes.

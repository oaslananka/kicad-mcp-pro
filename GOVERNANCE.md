# Governance

KiCad MCP Pro is maintained by `@oaslananka`. The project uses maintainer-led decisions with lazy consensus for routine changes.

## Decision Process

- Small fixes, docs updates, tests, and CI maintenance can be merged after normal review.
- User-facing behavior, public tool contracts, profile changes, transport behavior, and release policy changes need an issue or discussion before implementation.
- Major public API or workflow changes require an RFC under `docs/rfcs/`.

## RFC Process

1. Create `docs/rfcs/000N-title.md` with motivation, design, compatibility, migration, and alternatives.
2. Open a GitHub Discussion and keep it open for at least 14 days.
3. Maintainers accept, reject, or request revision.
4. Accepted RFCs become the source of truth for implementation PRs.

## Release Authority

Automated GitHub CI/CD is owned by the `oaslananka-lab/kicad-mcp-pro` mirror. Personal GitHub, Azure DevOps, and GitLab remain manual fallback surfaces.

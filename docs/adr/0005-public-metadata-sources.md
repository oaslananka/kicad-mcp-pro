# ADR-0005: Public Metadata Sources

**Status:** Accepted
**Date:** 2026-07-22
**Deciders:** @oaslananka

## Context

KiCad MCP Pro publishes support statements and repository metadata through several public surfaces: Python package metadata, `server.json`, the FAQ, the roadmap, registry submissions, and release artifacts. Hand-maintained copies had diverged, including a dropped KiCad line being described as supported, already-published versions appearing under upcoming work, and a stale GitHub repository identifier.

These values need explicit canonical sources and a deterministic check that runs before merge and release.

## Decision

The canonical public metadata sources are:

| Metadata | Canonical source |
| --- | --- |
| Package version | `pyproject.toml` (`project.version`) |
| Repository URL | `pyproject.toml` (`project.urls.Repository`) |
| Stable GitHub repository node ID | `pyproject.toml` (`tool.kicad-mcp.public-metadata.repository-id`) |
| KiCad support, deprecation, preview, and dropped-state policy | `compatibility.yaml` |
| MCP protocol contract | `compatibility.yaml` |
| Future roadmap commitments | Headings and content under `ROADMAP.md` → `Upcoming` |

`scripts/sync_mcp_metadata.py` renders or validates the derived public surfaces:

- `server.json`, including repository identity, package versions, registry URLs, and compatibility-aware prerequisites;
- `packages/mcp-npm/package.json` and `src/kicad_mcp/__init__.py`;
- the marked KiCad support block in `docs/faq.md`;
- the marked runtime-policy block in `ROADMAP.md`.

The roadmap remains editorial rather than fully generated. The metadata check rejects any semantic-version heading in the `Upcoming` section that is less than or equal to the current package version.

## Consequences

- Maintainers update canonical files rather than editing generated public metadata directly.
- KiCad support wording in the FAQ and registry manifest cannot silently diverge from `compatibility.yaml`.
- Repository transfers or recreation require an intentional update to the stable GitHub node ID.
- Release automation can refresh generated metadata with `pnpm run metadata:sync`.
- CI, pre-push hooks, and release dry-runs fail when generated metadata or roadmap state drifts.

## Verification

Run:

```bash
corepack pnpm run metadata:check
uv run --all-extras pytest -q tests/unit/test_public_metadata.py
```

To verify the repository identity against GitHub before changing it:

```bash
gh api repos/oaslananka/kicad-mcp-pro --jq '{url: .html_url, node_id}'
```

The checked values must match `project.urls.Repository` and `tool.kicad-mcp.public-metadata.repository-id` in `pyproject.toml`.

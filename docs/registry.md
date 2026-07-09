# MCP Registry status

KiCad MCP Pro publishes registry metadata from the repository-level `server.json` manifest.

## Canonical identity

| Field | Value |
| --- | --- |
| Registry name | `io.github.oaslananka/kicad-mcp-pro` |
| Repository | `https://github.com/oaslananka/kicad-mcp-pro` |
| Documentation | `https://oaslananka.github.io/kicad-mcp-pro/` |
| PyPI package | `kicad-mcp-pro` |
| npm package | `kicad-mcp-pro` |
| Current manifest version | `3.20.0` |

## Source of truth

- `server.json` is the registry manifest source of truth.
- `pyproject.toml`, package metadata, and `server.json` must stay synchronized.
- Registry publication should use the documented dry-run flow before any live publish.
- Live publication requires maintainer review and should not run from a dirty tree.

## Validation commands

Run these before registry submission or release handoff:

```bash
corepack pnpm run mcp:manifest:check
corepack pnpm run metadata:check
corepack pnpm run publish:mcp:dry-run
corepack pnpm run submission:check
```

The first two checks were verified locally while adding this page. The dry-run and submission checks remain the release operator's final gate because they may depend on network reachability and registry-side availability.

## CI coverage

`check:meta` includes `metadata:check` and `mcp:manifest:check`, so ordinary CI catches most metadata drift before release. Release readiness also runs `submission:check` through `check:release`.

## Related docs

- [OpenAI MCP Registry submission](submission/openai-mcp-registry.md)
- [Public listings](public-listing.md)
- [Release process](release-process.md)
- [MCP transport](mcp/transport.md)

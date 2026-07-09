# Maintainers

| Maintainer | Scope |
|---|---|
| `@oaslananka` | Project owner, release owner, security contact |

Future maintainers are added here with their review scope and release
permissions. The governance, succession, and security-response model is in
[`GOVERNANCE.md`](GOVERNANCE.md).

## Canonical identifiers (continuity anchors)

If maintenance has to be picked up by someone new, these are the project's
identities of record:

| Asset | Identifier |
|---|---|
| Source repository | `github.com/oaslananka/kicad-mcp-pro` |
| PyPI package | `kicad-mcp-pro` |
| npm package | `kicad-mcp-pro` |
| MCP Registry name | `io.github.oaslananka/kicad-mcp-pro` |

## Becoming a co-maintainer

Bus factor is currently 1; adding co-maintainers is the primary way we reduce it.
Candidates have typically:

- landed several merged PRs with tests across more than one subsystem;
- shown they respect the adapter-seam quarantine and the honesty principle
  (no tool claims a capability the code does not have); and
- run and understood `task ci` locally.

A co-maintainer is invited by an existing maintainer and, on acceptance, is added
to the table above and granted:

1. **Repository write** (review/merge) on `oaslananka/kicad-mcp-pro`.
2. **Release rights** via the GitHub Actions release environments — no local
   signing secrets are handed over; publishing is GitHub-side trusted publishing.
3. **Security triage** access (private vulnerability reports) per
   [`SECURITY.md`](SECURITY.md).

A new maintainer should confirm continuity by cutting one patch release end-to-end
and running `task ci` green before taking over solo coverage.

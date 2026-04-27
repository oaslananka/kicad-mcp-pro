# API Stability

KiCad MCP Pro treats public MCP tools, resource URIs, prompt names, server profiles, environment variables, and documented CLI behavior as public API.

## Stability Levels

- **Stable:** documented behavior used by normal clients.
- **Experimental:** hidden unless explicitly enabled or marked experimental in tool metadata.
- **Internal:** helpers, modules, and implementation details not documented for clients.

## Deprecation Policy

Stable API removals require:

1. A deprecation note in docs or changelog.
2. Runtime or discovery-visible warning when practical.
3. At least two minor releases before removal.

Security fixes may bypass the full deprecation window when preserving behavior would put users at risk.

## Breaking Changes

Breaking changes require a PR label, changelog entry, migration note, and, for major public workflow changes, an RFC.

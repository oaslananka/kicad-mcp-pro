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

## Live-preview workflow stability

`sch_live_preview()` is a documented agent workflow surface, but clients must
separate stable workflow semantics from evolving implementation metadata.

Stable for client use:

- baseline, no-change, debounce-pending, changed, and rendered status concepts;
- watched-file and changed-file evidence;
- rendered PNG artifact evidence when rendering succeeds;
- child-sheet inclusion as the default watch behavior;
- artifact-first safety guidance for companion-plugin and agent flows.

Evolving metadata:

- richer manifest files;
- additional visual-evidence artifact indexes;
- more detailed debounce timing fields;
- GUI-facing confirmation and session-consent metadata.

Clients should ignore unknown fields in live-preview responses and should not
parse human-readable messages when a structured field is available.

# Commit conventions

KiCad MCP Pro uses Conventional Commits so release automation can classify changes and generate changelog entries consistently.

## Format

```text
<type>(optional-scope): <summary>
```

Examples:

```text
fix(schematic): reject unknown symbols
feat(pcb): add placement quality report
docs(security): clarify private disclosure process
test(router): cover profile tool counts
chore(release): sync generated metadata
```

## Common types

| Type | Use for |
| --- | --- |
| `feat` | User-visible capability or public API addition. |
| `fix` | Bug fix or behavior correction. |
| `docs` | Documentation-only change. |
| `test` | Test or fixture change. |
| `refactor` | Internal restructuring without behavior change. |
| `chore` | Build, release, metadata, or maintenance change. |
| `ci` | Workflow or CI-only change. |
| `security` | Security hardening when `fix` is not specific enough. |

## DCO sign-off

Contributions use the Developer Certificate of Origin process described in `CONTRIBUTING.md`. Use `git commit -s` when practical.

## Breaking changes

Breaking public behavior must be discussed first and should include an issue or RFC, migration notes, tests, changelog/release-note entry, and compatibility matrix update when applicable.

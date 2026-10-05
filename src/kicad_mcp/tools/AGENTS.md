# MCP Tool Surface Instructions

These instructions apply to `src/kicad_mcp/tools/**` and supplement both parent agent instruction files.

## Boundary

This subtree exposes the public MCP tool surface. Tool names, schemas, annotations, profile membership, operating-mode restrictions, side effects, generated references, and agent-visible errors are compatibility and safety contracts.

Read before material changes:

- `ARCHITECTURE.md`
- `docs/agents/progressive-disclosure.md`
- `docs/tools-agent-workflow.md`
- `docs/development/testing-policy.md`
- `src/kicad_mcp/tools/router.py`
- `src/kicad_mcp/tools/metadata.py`
- `src/kicad_mcp/operating_modes.py`

## Registry and profile contract

`tools/router.py` is the registry of record for categories and profile membership.

When adding, removing, renaming, or moving a tool:

- update the correct `TOOL_CATEGORIES` entry;
- verify the intended `PROFILE_CATEGORIES` exposure;
- keep experimental classification explicit;
- preserve default/review/build/release progressive-disclosure guarantees;
- do not expose broad low-level mutation merely to make a workflow easier.

Profile controls discovery. Operating mode is an independent execution-risk gate. A broader profile must not silently bypass readonly/write/manufacturing/experimental mode policy.

## Metadata is executable policy

Treat tool annotations and metadata as behavior, not comments.

Preserve accurate semantics for:

- read-only versus mutating behavior;
- destructive behavior;
- headless/native capability requirements;
- KiCad-running requirements;
- runtime dependencies;
- human-only manufacturing controls;
- tool-effect/evidence metadata.

Do not reclassify a tool to avoid a confirmation, approval, profile, or operating-mode restriction.

## Mutation and manufacturing safety

Use the repository's bounded workflow model:

```text
inspect -> plan -> modify -> preview -> verify -> ERC/DRC/DFM -> export
```

- Keep write intent explicit.
- Preserve transaction, rollback, preview/apply, and post-write verification where implemented.
- Do not add ad-hoc direct `.kicad_pcb` or `.kicad_sch` rewriting that bypasses established services/adapters.
- Manufacturing package generation remains human-gated.
- A passed automated gate is evidence for that gate, not independent manufacturing approval.

## Schemas, errors, and generated surfaces

Public tool schemas and structured outputs must remain synchronized with implementation and generated contracts.

As applicable, update or verify:

- generated tool reference;
- tool-effect manifest;
- profile/toolset snapshots;
- adapter/capability matrices;
- tool-surface and registry-consistency tests;
- stable error codes and hints.

Generated files are outputs. Regenerate them from their canonical inputs rather than editing around drift.

## Verification

For tool-surface changes, use the focused repository checks:

```bash
pnpm run docs:tools:check
pnpm run tool-effects:check
pnpm run tool-contracts:check
pnpm run profiles:check
pnpm run toolsets:check
pnpm run architecture:check
task pre-push
```

Run the narrow unit/integration tests for the affected tool/domain and `task verify` before handoff when the pinned toolchain is available.

For behavior that depends on a live KiCad engine, use the dedicated KiCad-enabled CI/evidence path; contract mocks do not prove native runtime behavior.

## Definition of done

A tool change is complete only when implementation, registry membership, profile/mode exposure, annotations, schemas, generated contracts, error behavior, tests, and native evidence tell the same story.

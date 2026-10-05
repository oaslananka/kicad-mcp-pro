# KiCad MCP Server Instructions

These instructions apply to `src/kicad_mcp/**` and supplement the repository root `AGENTS.md`. The more specific `src/kicad_mcp/tools/AGENTS.md` also applies inside `tools/**`.

## Read first

Use the canonical sources rather than restating them here:

- `ARCHITECTURE.md`
- `docs/development/architecture.md`
- `docs/development/testing-policy.md`
- `docs/security/threat-model.md`
- `compatibility.yaml`

## Layering and dependency direction

Preserve the repository's five-layer architecture:

1. transport;
2. MCP protocol;
3. orchestration/profile/tool registration;
4. KiCad adapter seam;
5. pure domain logic.

Do not move KiCad-version fragility into pure domain code. Deterministic logic should remain testable without a KiCad process or import when the architecture permits it.

New PCB, schematic, validation, routing, signal-integrity, manufacturing, or project behavior should prefer the existing typed domain/service packages plus thin adapters. Keep composition roots focused on registration and wiring; do not rebuild monolithic `register()` functions.

## KiCad adapter seam

KiCad-facing fragility belongs behind the established seam:

- `kicad/`
- `connection.py`
- `ipc/`
- `discovery.py`
- bounded tool adapters that delegate to those interfaces

The supported channels into KiCad are intentional: `kicad-cli`, IPC/`kipy`, and validated S-expression/project-file handling. Do not invent a fourth ad-hoc channel or spread direct runtime internals into unrelated domain modules.

## Real-state and evidence rule

Never invent board, schematic, ERC/DRC, manufacturing, capability, or KiCad runtime state.

- Native claims must come from native KiCad/CLI/IPC evidence or repository-defined evidence records.
- Heuristic, approximate, first-pass, or partial calculations must remain labeled as such.
- Mocked/unit evidence is not live KiCad evidence.
- A timeout or lost connection during a mutation is not proof that state is unchanged; follow the established read-back/recovery semantics before retrying.
- Do not turn missing native capability into a fabricated success path.

## Filesystem and subprocess safety

Treat MCP arguments, paths, names, output locations, environment-controlled executables, and imported artifacts as untrusted.

- Keep filesystem access confined through the repository path-safety helpers.
- Preserve traversal, absolute/UNC path, symlink, extension, and destructive-operation checks.
- Keep subprocess execution argv-based with `shell=False`; do not introduce shell interpolation for user-controlled values.
- Revalidate destructive targets at the boundary where repository policy requires it.
- Security-sensitive filesystem/subprocess changes need hostile-input and failure-path tests.

## Errors and compatibility

Agent-visible failures should use the repository's typed error model and stable error codes instead of leaking arbitrary implementation exceptions.

Treat these as compatibility surfaces:

- MCP protocol/tool behavior;
- KiCad version/runtime requirements;
- public configuration and environment variables;
- Engineering Graph schema/identity semantics;
- desktop/backend compatibility fields;
- generated adapter/capability metadata.

Follow repository deprecation and compatibility policy rather than silently changing them.

## Verification

Run the smallest focused tests for the changed domain, then use:

```bash
task pre-push
task verify
```

When compatibility or adapter behavior changes, also run the repository-owned compatibility checks selected by `scripts/hook_pre_push.py` or explicitly:

```bash
pnpm run compat:check
pnpm run adapter-matrix:check
```

Live KiCad behavior requires the dedicated KiCad-enabled evidence path; do not claim live validation from unit tests alone.

## Definition of done

A server change is complete only when layer ownership, adapter boundaries, real-state semantics, path/subprocess safety, typed errors, compatibility metadata, tests, and evidence remain aligned.

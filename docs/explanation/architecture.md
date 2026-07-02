# Architecture explanation

KiCad MCP Pro is organized around a small number of boundaries that keep the tool safe, testable, and honest about what it can automate.

## Core idea

The MCP server exposes agent-facing tools, but KiCad-facing behavior is isolated behind adapter seams. Pure domain logic remains testable without KiCad; live KiCad or KiCad CLI/IPC integration is treated as an explicit runtime dependency.

## Why this matters

- Agent clients need predictable tool contracts.
- KiCad file formats and IPC APIs can change between KiCad releases.
- Destructive operations must remain explicit and auditable.
- Heuristic SI/PI/EMC/thermal checks must not be marketed as solver-grade signoff.

## Main layers

1. Transport and MCP protocol handling.
2. Tool registration and profile routing.
3. Orchestration and workflow helpers.
4. KiCad adapter seam for CLI, IPC, and S-expression files.
5. Pure domain logic and validation helpers.

## More detail

- High-level architecture: `ARCHITECTURE.md`
- Development architecture: `docs/development/architecture.md`
- ADRs: `docs/adr/README.md`
- Security threat model: `docs/security/threat-model.md`
- Input validation: `docs/security/input-validation.md`

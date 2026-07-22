# ADR-0007: KiCad Adapter Selection and SWIG Retirement

**Status:** Accepted
**Date:** 2026-07-22
**Deciders:** @oaslananka

## Context

KiCad 10.0.x is the stable release line for KiCad MCP Pro. KiCad 11 development builds add a
headless IPC server through `kicad-cli api-server`, while the legacy SWIG `pcbnew` Python bindings
are scheduled for removal. The repository already contains live IPC, CLI, guarded file, simulation,
routing, network, and Git execution paths, but their selection rules were distributed across tool
modules and runtime checks.

A hidden or opportunistic fallback is unsafe for EDA automation. An IPC mutation must not silently
become an unguarded text rewrite, an unavailable native export must not be emulated, and a preview
runtime must not be advertised as production-ready merely because one probe passed.

## Decision

Maintain a generated adapter matrix derived from the public tool router, the capability registry,
and explicit category policies. Every routed tool has exactly one category and receives a
deterministic runtime decision.

The selection order is:

1. Use KiCad 11 headless IPC only when headless mode is explicitly asserted and a KiCad 11 or
   later API server is reachable. A major version alone never implies a headless session.
2. Use GUI IPC, including KiCad 11 GUI sessions, when the required PCB or schematic document
   context is open.
3. Use only the adapter declared by the tool capability: `kicad-cli`, a guarded file writer, ngspice,
   FreeRouting, network access, Docker, Git, or a repository-local analytical engine.
4. Fail closed when the declared runtime is unavailable.

There is no SWIG fallback. Production imports or calls to `pcbnew` remain forbidden by
`scripts/check_no_pcbnew.py`.

## Mutation safety

- Schematic file mutations use atomic replacement and structural fingerprint loss detection. An
  unintentional removal restores the original file and raises an error.
- PCB file mutations use temporary-file replacement, parser validation, and transaction APIs where
  the IPC backend exposes them.
- KiCad 11 write readiness is tested with a no-op begin/drop transaction so the canary does not
  persist design changes.
- Native export canaries write to isolated artifact directories and require non-empty outputs.
- Manufacturing releases retain their existing human approval and evidence gates.

## Canary evidence

The scheduled KiCad preview workflow publishes separate artifacts for:

- `kicad-11-headless-read`
- `kicad-11-headless-write`
- `kicad-11-headless-export`

A surface is reported as `blocked` when the nightly package, `api-server`, or a compatible
`kicad-python` headless constructor is unavailable. A blocked preview report is evidence of the
current upstream boundary, not a passing support claim.

## Promotion gates

KiCad 11 remains preview-only until all of the following are true:

1. A KiCad 11 release candidate or stable build is available on supported CI runners.
2. A stable `kicad-python` release supports headless construction without repository patches.
3. Read, write, and export canaries pass independently on the same verified build.
4. Guarded file round-trip and transactional mutation tests remain green.
5. No production SWIG usage is detected.
6. `compatibility.yaml`, runtime documentation, and release notes are intentionally updated.

## Rollback

Disable the KiCad 11 preview lane and continue using the KiCad 10 GUI IPC, CLI, and guarded file
adapters. The adapter matrix contains no data migration and does not change the stable KiCad support
line, so rollback requires no project-file conversion.

## Consequences

Adapter decisions are machine-readable through server-info diagnostics and committed generated
artifacts. New tool categories cannot enter the router without an explicit adapter policy. The
repository gains honest prerelease evidence while avoiding a premature KiCad 11 support claim.

## Verification

```bash
corepack pnpm run adapter-matrix:check
corepack pnpm run compat:check
uv run --all-extras pytest -q \
  tests/unit/test_kicad_adapter_matrix.py \
  tests/unit/test_kicad11_headless_canary.py \
  tests/unit/test_schematic_write_integrity.py \
  tests/unit/test_schematic_write_transaction_guard.py
```

Sources:

- [KiCad command-line interface](https://docs.kicad.org/master/en/cli/cli.html)
- [KiCad IPC API status](https://dev-docs.kicad.org/en/apis-and-binding/ipc-api/)
- [KiCad PCB Python bindings](https://dev-docs.kicad.org/en/apis-and-binding/pcbnew/)

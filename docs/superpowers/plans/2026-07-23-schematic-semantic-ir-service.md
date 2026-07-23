# Schematic Semantic IR Service Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Extract `sch_get_circuit_ir` from the monolithic schematic FastMCP registry into a directly testable service and thin adapter without changing its public contract or lazy import behavior.

**Architecture:** Add one FastMCP-free semantic-IR service with structural protocols and injected parser/linter dependencies, plus one thin registration adapter. Keep `src/kicad_mcp/tools/schematic.py` as the composition root and retain lazy `kicad_mcp.ir` imports through dependency wrappers to avoid a circular import.

**Tech Stack:** Python 3.13, FastMCP, pytest, Ruff, mypy, Pyright, existing semantic IR and architecture tooling.

## Global Constraints

- Preserve the exact public tool name, signature, description, schema, annotations, ten-second TTL cache, lazy imports, log event, diagnostics, sorting, truncation, formatting, and result text.
- Do not change IR models, parser behavior, lint rules, output format, or runtime dependencies.
- Keep the adapter `register()` function at or below 300 lines.
- Keep domain code independent of FastMCP and `kicad_mcp.tools.schematic`.
- Keep the committed tool-surface snapshot unchanged.

---

### Task 1: Add the FastMCP-free semantic IR service

**Files:**
- Create: `src/kicad_mcp/schematic/semantic_ir.py`
- Create: `tests/unit/test_schematic_semantic_ir_service.py`

**Interfaces:**
- Consumes: active schematic lookup, circuit parser, lint engine, diagnostic wrapper, and parse-failure callback
- Produces: `SchematicSemanticIRService.get_summary() -> str`

- [x] Write direct tests for parse failure/logging/diagnostics, empty circuits, complete component/net/rail/interface rendering, stable sorting, truncation, DNP/NoBOM flags, voltage tags, and lint formatting.
- [x] Run the service test; expect collection failure because the module is absent.
- [x] Implement structural protocols and the minimal injected service while preserving legacy output byte-for-byte.
- [x] Re-run service tests; expect all pass.
- [x] Run Ruff, mypy, and scoped Pyright.
- [x] Commit with `refactor(schematic): extract semantic IR service`.

### Task 2: Add the thin adapter and composition wiring

**Files:**
- Create: `src/kicad_mcp/tools/schematic_semantic_ir.py`
- Create: `tests/unit/test_schematic_semantic_ir_registration.py`
- Modify: `src/kicad_mcp/tools/schematic.py`

**Interfaces:**
- Consumes: `SchematicSemanticIRService`
- Produces: `SchematicSemanticIRDependencies(service: SchematicSemanticIRService)`
- Produces: `register(mcp: FastMCP, dependencies: SchematicSemanticIRDependencies) -> None`

- [x] Write adapter tests for exact name, description, empty schema, headless metadata, delegation, and ten-second cache behavior.
- [x] Run the adapter test; expect collection failure because the adapter module is absent.
- [x] Implement the adapter and lazy parser/linter wrappers, wire the service in the composition root, and remove the nested legacy tool function.
- [x] Run service, adapter, focused integration, authoring-surface, and tool-surface tests.
- [x] Commit with `refactor(schematic): delegate semantic IR registration`.

### Task 3: Enforce architecture and public-contract stability

**Files:**
- Modify: `scripts/check_architecture_boundaries.py`
- Create: `tests/unit/test_schematic_semantic_ir_architecture.py`

- [x] Write failing architecture tests requiring the service and adapter to be tracked, forbidding monolith imports, and enforcing the 300-line limit.
- [x] Run the architecture test; expect failure because policy entries are absent.
- [x] Add the new modules to the architecture checker and rerun focused architecture plus the checker.
- [x] Compare exact full-server metadata against `main` and run the committed tool-surface snapshot.
- [x] Commit with `test(architecture): guard semantic IR boundaries`.

### Task 4: Record evidence and run repository gates

**Files:**
- Modify: `docs/superpowers/plans/2026-07-23-schematic-semantic-ir-service.md`

- [x] Run focused service/adapter coverage and require at least 83%.
- [x] Run formatting, Ruff, mypy, scoped Pyright, architecture, metadata/generated-doc checks, tool-surface snapshot, strict docs, latency, security, workflow, package, focused integration, and full unit gates.
- [x] Record exact metadata equality, focused/full test counts, coverage, register spans, and gate outcomes.
- [x] Commit with `docs(architecture): record semantic IR evidence`.

## Verification Evidence

- TDD red/green evidence was observed for the absent service, absent adapter, and missing architecture-policy entries before implementation.
- Focused service and adapter suite: 6 tests passed; focused integration, architecture, registration, service, and authoring-surface suite: 12 tests passed.
- Focused coverage: 117 statements, 100% total (`semantic_ir.py` 101/101; `schematic_semantic_ir.py` 16/16), exceeding the 83% requirement.
- Exact full-server metadata matches `main` for name, description, input schema, output schema, annotations, MCP metadata, and headless/KiCad-running metadata.
- Committed tool-surface snapshot passed unchanged.
- Main schematic `register()` span decreased from 1,745 lines on `main` to 1,657 lines; the new adapter `register()` is 18 lines.
- Full selected unit gate passed: 1,733 tests collected, 5 skipped, no failures.
- Focused schematic integration test passed on a populated schematic.
- Formatting, Ruff, mypy, scoped Pyright, architecture, metadata, generated references, parity, profile, tool-contract, compatibility, runtime-policy, strict MkDocs, latency benchmark, Bandit, dependency audit, GitHub Actions policy, zizmor, actionlint workflow checks, package build, and package metadata checks all passed.
- The repository bootstrap reproduced the known `actionlint-py` wheel-install `EPERM` on the exec-agent filesystem. Verification used the locked environment with `uv sync --all-extras --frozen --no-install-package actionlint-py` and the exact cached actionlint binary; no source or lockfile changes were required.

### Task 5: Open, review, and merge the pull request

- [ ] Push and open a professional English PR referencing #434.
- [ ] Inspect CI, bot comments, reviews, and review threads.
- [ ] Address every actionable finding and rerun affected checks.
- [ ] Merge only after required checks pass and the merge state is clean.
- [ ] Update `main` and remove the worktree and local/remote topic branch.

# Schematic Semantic IR Service Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

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

- [ ] Write direct tests for parse failure/logging/diagnostics, empty circuits, complete component/net/rail/interface rendering, stable sorting, truncation, DNP/NoBOM flags, voltage tags, and lint formatting.
- [ ] Run the service test; expect collection failure because the module is absent.
- [ ] Implement structural protocols and the minimal injected service while preserving legacy output byte-for-byte.
- [ ] Re-run service tests; expect all pass.
- [ ] Run Ruff, mypy, and scoped Pyright.
- [ ] Commit with `refactor(schematic): extract semantic IR service`.

### Task 2: Add the thin adapter and composition wiring

**Files:**
- Create: `src/kicad_mcp/tools/schematic_semantic_ir.py`
- Create: `tests/unit/test_schematic_semantic_ir_registration.py`
- Modify: `src/kicad_mcp/tools/schematic.py`

**Interfaces:**
- Consumes: `SchematicSemanticIRService`
- Produces: `SchematicSemanticIRDependencies(service: SchematicSemanticIRService)`
- Produces: `register(mcp: FastMCP, dependencies: SchematicSemanticIRDependencies) -> None`

- [ ] Write adapter tests for exact name, description, empty schema, headless metadata, delegation, and ten-second cache behavior.
- [ ] Run the adapter test; expect collection failure because the adapter module is absent.
- [ ] Implement the adapter and lazy parser/linter wrappers, wire the service in the composition root, and remove the nested legacy tool function.
- [ ] Run service, adapter, focused integration, authoring-surface, and tool-surface tests.
- [ ] Commit with `refactor(schematic): delegate semantic IR registration`.

### Task 3: Enforce architecture and public-contract stability

**Files:**
- Modify: `scripts/check_architecture_boundaries.py`
- Create: `tests/unit/test_schematic_semantic_ir_architecture.py`

- [ ] Write failing architecture tests requiring the service and adapter to be tracked, forbidding monolith imports, and enforcing the 300-line limit.
- [ ] Run the architecture test; expect failure because policy entries are absent.
- [ ] Add the new modules to the architecture checker and rerun focused architecture plus the checker.
- [ ] Compare exact full-server metadata against `main` and run the committed tool-surface snapshot.
- [ ] Commit with `test(architecture): guard semantic IR boundaries`.

### Task 4: Record evidence and run repository gates

**Files:**
- Modify: `docs/superpowers/plans/2026-07-23-schematic-semantic-ir-service.md`

- [ ] Run focused service/adapter coverage and require at least 83%.
- [ ] Run formatting, Ruff, mypy, scoped Pyright, architecture, metadata/generated-doc checks, tool-surface snapshot, strict docs, latency, security, workflow, package, focused integration, and full unit gates.
- [ ] Record exact metadata equality, focused/full test counts, coverage, register spans, and gate outcomes.
- [ ] Commit with `docs(architecture): record semantic IR evidence`.

### Task 5: Open, review, and merge the pull request

- [ ] Push and open a professional English PR referencing #434.
- [ ] Inspect CI, bot comments, reviews, and review threads.
- [ ] Address every actionable finding and rerun affected checks.
- [ ] Merge only after required checks pass and the merge state is clean.
- [ ] Update `main` and remove the worktree and local/remote topic branch.

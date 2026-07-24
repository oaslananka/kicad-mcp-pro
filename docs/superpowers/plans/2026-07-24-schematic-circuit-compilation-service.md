# Schematic Circuit Compilation Service Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract `sch_analyze_net_compilation` and `sch_build_circuit` from the monolithic schematic FastMCP registry into a directly testable service and thin adapter without changing public contracts or generated schematic behavior.

**Architecture:** Add one FastMCP-free circuit-compilation service with a prepared-input data object and explicit injected dependencies, plus one thin registration adapter. Keep `src/kicad_mcp/tools/schematic.py` as the composition root and inject lazy wrappers around current helpers to preserve monkeypatch compatibility.

**Tech Stack:** Python 3.13, FastMCP, Pydantic models, pytest, Ruff, mypy, Pyright, existing schematic netlist and architecture tooling.

## Global Constraints

- Preserve exact public names, signatures, descriptions, schemas, annotations, validation/error text, warning events, generated schematic text, transaction flags, reload ordering, and result notes.
- Do not change routing, auto-layout, validation, symbol lookup, paper handling, or serialization algorithms.
- Keep the adapter `register()` function at or below 300 lines.
- Keep domain code independent of FastMCP and `kicad_mcp.tools.schematic`.
- Keep the committed tool-surface snapshot unchanged.

---

### Task 1: Add the FastMCP-free circuit compilation service

**Files:**
- Create: `src/kicad_mcp/schematic/circuit_compilation.py`
- Create: `tests/unit/test_schematic_circuit_compilation_service.py`

- [ ] Write direct tests for analysis delegation, empty builds, unresolved warnings/errors, paper preservation/growth, library deduplication, generated elements, transaction flags, reload ordering, and result notes.
- [ ] Run the service test; expect collection failure because the module is absent.
- [ ] Implement `PreparedCircuitInputs` and the minimal injected service while preserving legacy behavior byte-for-byte.
- [ ] Re-run service tests; expect all pass.
- [ ] Run Ruff, mypy, and scoped Pyright.
- [ ] Commit with `refactor(schematic): extract circuit compilation service`.

### Task 2: Add the thin adapter and composition wiring

**Files:**
- Create: `src/kicad_mcp/tools/schematic_circuit_compilation.py`
- Create: `tests/unit/test_schematic_circuit_compilation_registration.py`
- Modify: `src/kicad_mcp/tools/schematic.py`

- [ ] Write adapter tests for exact names, descriptions, schemas, annotations, and delegation.
- [ ] Run the adapter test; expect collection failure because the adapter module is absent.
- [ ] Implement the adapter, wire lazy compatibility dependencies in the composition root, and remove the two nested legacy functions.
- [ ] Run service, adapter, focused integration, authoring-surface, and tool-surface tests.
- [ ] Commit with `refactor(schematic): delegate circuit compilation registration`.

### Task 3: Enforce architecture and public-contract stability

**Files:**
- Modify: `scripts/check_architecture_boundaries.py`
- Create: `tests/unit/test_schematic_circuit_compilation_architecture.py`

- [ ] Write failing architecture tests requiring the service and adapter to be tracked, forbidding monolith imports, and enforcing the 300-line limit.
- [ ] Run the architecture test; expect failure because policy entries are absent.
- [ ] Add the new modules to the architecture checker and rerun focused architecture plus the checker.
- [ ] Compare exact full-server metadata for both tools against `main` and run the committed tool-surface snapshot.
- [ ] Commit with `test(architecture): guard circuit compilation boundaries`.

### Task 4: Record evidence and run repository gates

**Files:**
- Modify: `docs/superpowers/plans/2026-07-24-schematic-circuit-compilation-service.md`

- [ ] Run focused service/adapter coverage and require at least 83%.
- [ ] Run formatting, Ruff, mypy, scoped Pyright, architecture, metadata/generated-doc checks, tool-surface snapshot, strict docs, latency, security, workflow, package, focused integration, and full unit gates.
- [ ] Record exact metadata equality, focused/full test counts, coverage, register spans, and gate outcomes.
- [ ] Commit with `docs(architecture): record circuit compilation evidence`.

### Task 5: Open, review, and merge the pull request

- [ ] Push and open a professional English PR referencing #434.
- [ ] Inspect CI, bot comments, reviews, and review threads.
- [ ] Address every actionable finding and rerun affected checks.
- [ ] Merge only after required checks pass and the merge state is clean.
- [ ] Update `main` and remove the worktree and local/remote topic branch.

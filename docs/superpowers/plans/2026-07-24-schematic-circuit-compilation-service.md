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

- [x] Write direct tests for analysis delegation, empty builds, unresolved warnings/errors, paper preservation/growth, library deduplication, generated elements, transaction flags, reload ordering, and result notes.
- [x] Run the service test; expect collection failure because the module is absent.
- [x] Implement `PreparedCircuitInputs` and the minimal injected service while preserving legacy behavior byte-for-byte.
- [x] Re-run service tests; expect all pass.
- [x] Run Ruff, mypy, and scoped Pyright.
- [x] Commit with `refactor(schematic): extract circuit compilation service`.

### Task 2: Add the thin adapter and composition wiring

**Files:**
- Create: `src/kicad_mcp/tools/schematic_circuit_compilation.py`
- Create: `tests/unit/test_schematic_circuit_compilation_registration.py`
- Modify: `src/kicad_mcp/tools/schematic.py`

- [x] Write adapter tests for exact names, descriptions, schemas, annotations, and delegation.
- [x] Run the adapter test; expect collection failure because the adapter module is absent.
- [x] Implement the adapter, wire lazy compatibility dependencies in the composition root, and remove the two nested legacy functions.
- [x] Run service, adapter, focused integration, authoring-surface, and tool-surface tests.
- [x] Commit with `refactor(schematic): delegate circuit compilation registration`.

### Task 3: Enforce architecture and public-contract stability

**Files:**
- Modify: `scripts/check_architecture_boundaries.py`
- Create: `tests/unit/test_schematic_circuit_compilation_architecture.py`

- [x] Write failing architecture tests requiring the service and adapter to be tracked, forbidding monolith imports, and enforcing the 300-line limit.
- [x] Run the architecture test; expect failure because policy entries are absent.
- [x] Add the new modules to the architecture checker and rerun focused architecture plus the checker.
- [x] Compare exact full-server metadata for both tools against `main` and run the committed tool-surface snapshot.
- [x] Commit with `test(architecture): guard circuit compilation boundaries`.

### Task 4: Record evidence and run repository gates

**Files:**
- Modify: `docs/superpowers/plans/2026-07-24-schematic-circuit-compilation-service.md`

- [x] Run focused service/adapter coverage and require at least 83%.
- [x] Run formatting, Ruff, mypy, scoped Pyright, architecture, metadata/generated-doc checks, tool-surface snapshot, strict docs, latency, security, workflow, package, focused integration, and full unit gates.
- [x] Record exact metadata equality, focused/full test counts, coverage, register spans, and gate outcomes.
- [x] Commit with `docs(architecture): record circuit compilation evidence`.

## Verification Evidence

- TDD red/green evidence was observed for the absent service, absent adapter, and missing architecture-policy entries before implementation.
- Direct service, adapter, and architecture suites passed; focused schematic integration and committed tool-surface tests passed unchanged.
- Focused coverage is 100%: 126 statements (`circuit_compilation.py` 110 and `schematic_circuit_compilation.py` 16), with no missed lines.
- Exact full-server metadata matches `main` for both tools, including names, descriptions, input/output schemas, annotations, MCP metadata, and compatibility metadata.
- The monolithic schematic `register()` span decreased from 1,368 lines on `main` to 1,110 lines; the new adapter `register()` is 85 lines.
- Full selected unit gate passed: 1,765 tests selected from 1,768 collected, 5 skipped, no failures.
- Formatting, Ruff, mypy, scoped Pyright, architecture, metadata/generated references, parity, profile, tool-contract, compatibility, runtime-policy, strict MkDocs, latency benchmark, Bandit, dependency audit, GitHub Actions policy, zizmor, actionlint workflow checks, package build, and package metadata checks all passed.
- The repository bootstrap reproduced the known `actionlint-py` wheel-install `EPERM` on the exec-agent filesystem. Verification used the locked environment with `uv sync --all-extras --frozen --no-install-package actionlint-py` and the exact cached actionlint binary; no source or lockfile changes were required.

### Task 5: Open, review, and merge the pull request

- [ ] Push and open a professional English PR referencing #434.
- [ ] Inspect CI, bot comments, reviews, and review threads.
- [ ] Address every actionable finding and rerun affected checks.
- [ ] Merge only after required checks pass and the merge state is clean.
- [ ] Update `main` and remove the worktree and local/remote topic branch.
